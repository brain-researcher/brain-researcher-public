import fs from 'fs'
import path from 'path'
import { performance } from 'perf_hooks'

import {
  DatasetCardResponse,
  DatasetDetailResponse,
  DatasetSearchResponse,
  FacetValueResponse,
} from '@/types/datasets-search'

type CatalogRecord = {
  dataset_id: string
  name: string
  short_name?: string
  alias?: string[]
  description?: string
  category?: string
  modalities: string[]
  acquisitions: string[]
  subjects_count?: number
  sessions_count?: number
  species?: string[]
  age_range?: { min: number; max: number; units: string }
  disease_flags?: string[]
  subject_labels?: string[]
  phenotype_summary?: Array<{
    name: string
    column?: string
    category: string
    measurement_type?: string
    total_observations: number
    unique_subjects?: number
    distinct_values?: number
    value_counts?: Record<string, number>
    numeric_summary?: {
      min?: number
      max?: number
      mean?: number
      median?: number
    }
  }>
  annotation_sources?: string[]
  annotation_updated_at?: string
  center?: string
  consortium?: string
  source_repo: string
  source_repo_id?: string
  primary_url?: string
  access_type?: string
  license?: string
  approx_size_bytes?: number
  size_human?: string
  tags?: string[]
  tasks?: string[]
  has_derivatives?: boolean
  preview_media?: Array<{ kind: string; uri: string; label?: string }>
  created_from?: string
  source_version?: string
  created_at?: string
  updated_at?: string
  principal_investigator?: string
  onvoc?: { ids: string[]; labels?: string[] }
  tr_seconds?: number
  tr_sec?: number
  tr?: number
  voxel_mm?: number
  voxel_size_mm?: number
  voxel_size?: number | number[]
}

interface SearchParams {
  query?: string | null
  modalities?: string[]
  acquisitions?: string[]
  source_repo?: string[]
  access_type?: string[]
  category?: string[]
  tags?: string[]
  center?: string[]
  consortium?: string[]
  limit: number
  offset: number
  sort: 'relevance' | 'subjects' | 'updated'
  min_subjects?: number
  max_subjects?: number
  age_min?: number
  age_max?: number
  tr_min?: number
  tr_max?: number
  voxel_min?: number
  voxel_max?: number
}

const DATASET_CATALOG_FILENAME = process.env.BRAIN_RESEARCHER_DATASET_CATALOG_FILENAME || 'catalog.v1.jsonl'
const DATASET_CATALOG_CANDIDATES = [
  process.env.BRAIN_RESEARCHER_DATASET_CATALOG,
  path.resolve(process.cwd(), 'configs', 'datasets', DATASET_CATALOG_FILENAME),
  path.resolve(process.cwd(), '..', 'configs', 'datasets', DATASET_CATALOG_FILENAME),
  path.resolve(process.cwd(), '..', '..', 'configs', 'datasets', DATASET_CATALOG_FILENAME),
  path.resolve(process.cwd(), '..', '..', '..', 'configs', 'datasets', DATASET_CATALOG_FILENAME),
].filter(Boolean) as string[]

let cache: {
  records: CatalogRecord[]
  mtimeMs: number
  loadedAt: number
  support: {
    subjects: boolean
    age: boolean
    tr: boolean
    voxel: boolean
  }
} | null = null
let missingCatalogLogged = false
let onvocCache:
  | {
      lookup: Record<string, { ids: string[]; labels?: string[] }>
      mtimeMs: number
    }
  | null = null

const CROSSWALK_PATH = path.resolve(
  process.cwd(),
  '..',
  '..',
  '..',
  'brain_researcher',
  'services',
  'neurokg',
  'mappings',
  'onvoc_crosswalk.yaml',
)
const ONVOC_CONCEPTS_PATH = path.resolve(
  process.cwd(),
  '..',
  '..',
  '..',
  'data',
  'ontologies',
  'onvoc',
  'onvoc_concepts.json',
)

const emptyArray = () => [] as string[]

function sanitizeSizeHuman(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  if (!trimmed || /\bnan\b/i.test(trimmed) || /^n\/?a$/i.test(trimmed)) return undefined
  return trimmed
}

function sanitizeFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function getTrSeconds(record: CatalogRecord): number | null {
  const value = record.tr_seconds ?? record.tr_sec ?? record.tr
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function getVoxelMm(record: CatalogRecord): number | null {
  const value = record.voxel_mm ?? record.voxel_size_mm ?? record.voxel_size
  if (Array.isArray(value)) {
    const numeric = value.filter((v) => typeof v === 'number' && Number.isFinite(v))
    return numeric.length ? Math.max(...numeric) : null
  }
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function normalizeAgeRange(range?: { min?: number; max?: number; units?: string }) {
  if (!range) return null
  const unit = range.units?.toLowerCase() ?? 'years'
  const factor = (() => {
    if (unit.startsWith('year')) return 1
    if (unit.startsWith('month')) return 1 / 12
    if (unit.startsWith('day')) return 1 / 365
    return null
  })()
  if (!factor) return null
  const min = typeof range.min === 'number' ? range.min * factor : null
  const max = typeof range.max === 'number' ? range.max * factor : null
  if (min == null && max == null) return null
  return { min: min ?? max ?? 0, max: max ?? min ?? 0 }
}

function computeSupport(records: CatalogRecord[]) {
  return records.reduce(
    (acc, record) => {
      if (record.subjects_count != null) acc.subjects = true
      if (record.age_range?.min != null || record.age_range?.max != null) acc.age = true
      if (getTrSeconds(record) != null) acc.tr = true
      if (getVoxelMm(record) != null) acc.voxel = true
      return acc
    },
    { subjects: false, age: false, tr: false, voxel: false },
  )
}

function resolveCatalogPath(): string | null {
  for (const candidate of DATASET_CATALOG_CANDIDATES) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate
    }
  }
  return null
}

function readCatalog(): CatalogRecord[] {
  const file = resolveCatalogPath()
  if (!file) {
    if (!missingCatalogLogged) {
      console.warn(
        `[dataset-catalog] Catalog file not found. Set BRAIN_RESEARCHER_DATASET_CATALOG or ensure configs/datasets/${DATASET_CATALOG_FILENAME} exists.`,
      )
      missingCatalogLogged = true
    }
    cache = { records: [], mtimeMs: 0, loadedAt: Date.now(), support: { subjects: false, age: false, tr: false, voxel: false } }
    return cache.records
  }
  missingCatalogLogged = false
  const stats = fs.statSync(file)
  if (cache && cache.mtimeMs === stats.mtimeMs) {
    return cache.records
  }

  const raw = fs.readFileSync(file, 'utf-8')
  const records: CatalogRecord[] = raw
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))

  cache = {
    records,
    mtimeMs: stats.mtimeMs,
    loadedAt: Date.now(),
    support: computeSupport(records),
  }
  return records
}

function loadOnvocLookup(): Record<string, { ids: string[]; labels?: string[] }> {
  const crosswalkFile = CROSSWALK_PATH
  if (!fs.existsSync(crosswalkFile)) return {}
  const stat = fs.statSync(crosswalkFile)
  if (onvocCache && onvocCache.mtimeMs === stat.mtimeMs) {
    return onvocCache.lookup
  }

  const yaml = require('js-yaml')
  const crosswalk = yaml.load(fs.readFileSync(crosswalkFile, 'utf-8')) || {}
  const datasets = crosswalk.datasets || {}
  const lookup: Record<string, { ids: string[]; labels?: string[] }> = {}

  let idToLabel: Record<string, string> | null = null
  if (fs.existsSync(ONVOC_CONCEPTS_PATH)) {
    try {
      const concepts = JSON.parse(fs.readFileSync(ONVOC_CONCEPTS_PATH, 'utf-8'))
      idToLabel = Object.fromEntries(concepts.map((c: any) => [c.id, c.label || c.id]))
    } catch {
      idToLabel = null
    }
  }

  for (const [dsId, entry] of Object.entries<any>(datasets)) {
    const ids = entry?.primary ? [String(entry.primary)] : []
    const labels = ids.length && idToLabel ? ids.map((i) => idToLabel![i]).filter(Boolean) : undefined
    lookup[dsId] = { ids, labels }
  }

  onvocCache = { lookup, mtimeMs: stat.mtimeMs }
  return lookup
}

function buildSearchBlob(record: CatalogRecord): string {
  const parts: string[] = [record.name]
  parts.push(record.dataset_id)
  if (record.short_name) parts.push(record.short_name)
  if (record.source_repo_id) parts.push(record.source_repo_id)
  parts.push(...(record.alias ?? []))
  if (record.description) parts.push(record.description)
  if (record.center) parts.push(record.center)
  if (record.consortium) parts.push(record.consortium)
  if (record.principal_investigator) parts.push(record.principal_investigator)
  if (record.category) parts.push(record.category)
  parts.push(...(record.tags ?? []))
  parts.push(...(record.tasks ?? []))
  parts.push(...(record.species ?? []))
  parts.push(...(record.subject_labels ?? []))
  ;(record.phenotype_summary ?? []).forEach((item) => {
    if (item?.name) parts.push(item.name)
    if (item?.value_counts) parts.push(...Object.keys(item.value_counts))
  })
  parts.push(...record.modalities)
  parts.push(record.source_repo)
  return parts.join(' \n')
}

function matches(record: CatalogRecord, params: SearchParams): boolean {
  const {
    query,
    modalities,
    acquisitions,
    source_repo,
    access_type,
    category,
    tags,
    center,
    consortium,
    min_subjects,
    max_subjects,
    age_min,
    age_max,
    tr_min,
    tr_max,
    voxel_min,
    voxel_max,
  } = params

  if (query && query.trim()) {
    const blob = buildSearchBlob(record).toLowerCase()
    const tokens = query
      .toLowerCase()
      .split(/\s+/)
      .map((token) => token.trim())
      .filter(Boolean)
    if (tokens.length && !tokens.every((token) => blob.includes(token))) {
      return false
    }
  }

  if (modalities && modalities.length) {
    const recordModalities = new Set(record.modalities.map((m) => m.toLowerCase()))
    const searchSet = modalities.map((m) => m.toLowerCase())
    if (!searchSet.every((m) => recordModalities.has(m))) {
      return false
    }
  }

  if (acquisitions && acquisitions.length) {
    const recordAcq = new Set((record.acquisitions ?? []).map((a) => a.toLowerCase()))
    const searchSet = acquisitions.map((a) => a.toLowerCase())
    if (!searchSet.every((a) => recordAcq.has(a))) {
      return false
    }
  }

  if (source_repo && source_repo.length && !source_repo.map((s) => s.toLowerCase()).includes(record.source_repo.toLowerCase())) {
    return false
  }

  if (access_type && access_type.length) {
    const recordAccess = record.access_type?.toLowerCase() ?? ''
    if (!access_type.map((a) => a.toLowerCase()).includes(recordAccess)) {
      return false
    }
  }

  if (category && category.length) {
    const recordCategory = record.category?.toLowerCase() ?? ''
    if (!category.map((c) => c.toLowerCase()).includes(recordCategory)) {
      return false
    }
  }

  if (tags && tags.length) {
    const recordTags = new Set((record.tags ?? []).map((t) => t.toLowerCase()))
    if (!tags.map((t) => t.toLowerCase()).every((tag) => recordTags.has(tag))) {
      return false
    }
  }

  if (center && center.length) {
    const recordCenter = record.center?.toLowerCase() ?? ''
    if (!center.map((c) => c.toLowerCase()).includes(recordCenter)) {
      return false
    }
  }

  if (consortium && consortium.length) {
    const recordConsortium = record.consortium?.toLowerCase() ?? ''
    if (!consortium.map((c) => c.toLowerCase()).includes(recordConsortium)) {
      return false
    }
  }

  if (min_subjects != null || max_subjects != null) {
    if (record.subjects_count == null) return false
    if (min_subjects != null && record.subjects_count < min_subjects) return false
    if (max_subjects != null && record.subjects_count > max_subjects) return false
  }

  if (age_min != null || age_max != null) {
    const range = normalizeAgeRange(record.age_range)
    if (!range) return false
    if (age_min != null && range.min < age_min) return false
    if (age_max != null && range.max > age_max) return false
  }

  if (tr_min != null || tr_max != null) {
    const trSeconds = getTrSeconds(record)
    if (trSeconds == null) return false
    if (tr_min != null && trSeconds < tr_min) return false
    if (tr_max != null && trSeconds > tr_max) return false
  }

  if (voxel_min != null || voxel_max != null) {
    const voxel = getVoxelMm(record)
    if (voxel == null) return false
    if (voxel_min != null && voxel < voxel_min) return false
    if (voxel_max != null && voxel > voxel_max) return false
  }

  return true
}

function scoreRecord(record: CatalogRecord, query: string | null, sort: SearchParams['sort']): number {
  const base = (() => {
    if (!query) return 1
    const blob = buildSearchBlob(record).toLowerCase()
    return blob.includes(query.toLowerCase()) ? 1 : 0
  })()

  const subjects = record.subjects_count ?? 0
  const sessions = record.sessions_count ?? 0
  const recency = record.updated_at || record.created_at
  const recencyBonus = recency ? 0.1 : 0

  if (sort === 'subjects') {
    return subjects
  }

  if (sort === 'updated') {
    if (!recency) return 0
    const timestamp = Date.parse(recency)
    return Number.isNaN(timestamp) ? 0 : timestamp
  }

  return base + subjects * 0.001 + sessions * 0.0005 + recencyBonus
}

function toCard(record: CatalogRecord, score?: number): DatasetCardResponse {
  const onvocLookup = loadOnvocLookup()
  const onvoc =
    onvocLookup[record.dataset_id] ||
    (record.source_repo_id ? onvocLookup[record.source_repo_id] : undefined) ||
    (record.short_name ? onvocLookup[record.short_name] : undefined)
  return {
    id: record.dataset_id,
    name: record.name,
    description: record.description,
    category: record.category,
    modalities: record.modalities,
    acquisitions: record.acquisitions ?? [],
    subjects_count: record.subjects_count,
    sessions_count: record.sessions_count,
    access_type: record.access_type ?? 'public',
    license: record.license ?? 'CC0',
    source_repo: record.source_repo,
    source_repo_id: record.source_repo_id,
    primary_url: record.primary_url ?? '',
    center: record.center,
    consortium: record.consortium,
    tags: record.tags ?? [],
    tasks: record.tasks ?? [],
    has_derivatives: record.has_derivatives ?? false,
    preview_media: record.preview_media ?? [],
    onvoc,
    score,
    size_human: sanitizeSizeHuman(record.size_human),
    created_at: record.created_at,
    updated_at: record.updated_at,
  }
}

function toDetail(record: CatalogRecord): DatasetDetailResponse {
  const card = toCard(record)
  return {
    ...card,
    species: record.species ?? ['human'],
    age_range: record.age_range,
    disease_flags: record.disease_flags ?? [],
    subject_labels: record.subject_labels ?? [],
    phenotype_summary: record.phenotype_summary ?? [],
    annotation_sources: record.annotation_sources ?? [],
    annotation_updated_at: record.annotation_updated_at,
    approx_size_bytes: sanitizeFiniteNumber(record.approx_size_bytes),
    size_human: sanitizeSizeHuman(record.size_human),
    created_from: record.created_from,
    source_version: record.source_version,
    search_blob: buildSearchBlob(record),
  }
}

function makeFacet(values: Array<[string, number]>): FacetValueResponse[] {
  return values
    .filter(([value]) => Boolean(value))
    .map(([value, count]) => ({ value, count }))
}

function computeFacets(records: CatalogRecord[]): Record<string, FacetValueResponse[]> {
  const facets: Record<string, Map<string, number>> = {
    modalities: new Map(),
    source_repo: new Map(),
    access_type: new Map(),
    category: new Map(),
    tags: new Map(),
  }

  records.forEach((record) => {
    record.modalities.forEach((mod) => facets.modalities.set(mod, (facets.modalities.get(mod) ?? 0) + 1))
    facets.source_repo.set(record.source_repo, (facets.source_repo.get(record.source_repo) ?? 0) + 1)
    if (record.access_type) {
      facets.access_type.set(record.access_type, (facets.access_type.get(record.access_type) ?? 0) + 1)
    }
    if (record.category) {
      facets.category.set(record.category, (facets.category.get(record.category) ?? 0) + 1)
    }
    ;(record.tags ?? []).forEach((tag) => facets.tags.set(tag, (facets.tags.get(tag) ?? 0) + 1))
  })

  return Object.fromEntries(
    Object.entries(facets).map(([key, map]) => [
      key,
      makeFacet(Array.from(map.entries()).sort((a, b) => b[1] - a[1])),
    ]),
  )
}

export function searchCatalog(params: SearchParams): DatasetSearchResponse {
  const start = performance.now()
  const records = readCatalog()
  const support = cache?.support ?? computeSupport(records)
  const warnings: string[] = []
  const effectiveParams: SearchParams = { ...params }

  if ((params.min_subjects != null || params.max_subjects != null) && !support.subjects) {
    warnings.push('Subjects count filters are not available in the current dataset catalog.')
    delete effectiveParams.min_subjects
    delete effectiveParams.max_subjects
  }

  if ((params.age_min != null || params.age_max != null) && !support.age) {
    warnings.push('Age filters are not available in the current dataset catalog.')
    delete effectiveParams.age_min
    delete effectiveParams.age_max
  }

  if ((params.tr_min != null || params.tr_max != null) && !support.tr) {
    warnings.push('TR filters are not available in the current dataset catalog.')
    delete effectiveParams.tr_min
    delete effectiveParams.tr_max
  }

  if ((params.voxel_min != null || params.voxel_max != null) && !support.voxel) {
    warnings.push('Voxel size filters are not available in the current dataset catalog.')
    delete effectiveParams.voxel_min
    delete effectiveParams.voxel_max
  }

  const filtered = records.filter((record) => matches(record, effectiveParams))

  const scored = filtered.map((record) => ({
    record,
    score: scoreRecord(record, params.query ?? null, params.sort),
  }))

  scored.sort((a, b) => b.score - a.score)

  const total = scored.length
  const window = scored.slice(params.offset, params.offset + params.limit)
  const datasets = window.map(({ record, score }) => toCard(record, score))
  const facets = computeFacets(filtered)

  return {
    datasets,
    total,
    limit: params.limit,
    offset: params.offset,
    has_more: params.offset + params.limit < total,
    search_time_ms: Math.round(performance.now() - start),
    facets,
    last_updated: new Date(cache?.loadedAt ?? Date.now()).toISOString(),
    warnings: warnings.length ? warnings : undefined,
  }
}

export function getDataset(datasetId: string): DatasetDetailResponse | null {
  const query = String(datasetId || '').trim().toLowerCase()
  if (!query) return null

  const records = readCatalog()

  const exact = records.find((item) => item.dataset_id.toLowerCase() === query)
  if (exact) return toDetail(exact)

  const bySourceRepoId = records.find(
    (item) => String(item.source_repo_id || '').trim().toLowerCase() === query,
  )
  if (bySourceRepoId) return toDetail(bySourceRepoId)

  const byAlias = records.find((item) =>
    Array.isArray(item.alias)
      ? item.alias.some((alias) => String(alias).trim().toLowerCase() === query)
      : false,
  )
  if (byAlias) return toDetail(byAlias)

  const bySuffix = records.find((item) => {
    const parts = item.dataset_id.split(':').filter(Boolean)
    const suffix = parts.at(-1)?.toLowerCase()
    return suffix === query
  })
  if (bySuffix) return toDetail(bySuffix)

  const matchDsToken = query.match(/ds\d{6}/i)
  if (matchDsToken) {
    const token = matchDsToken[0].toLowerCase()
    const byDsToken = records.find((item) => {
      const id = item.dataset_id.toLowerCase()
      const sourceRepoId = String(item.source_repo_id || '').toLowerCase()
      return id.endsWith(`:${token}`) || sourceRepoId === token
    })
    if (byDsToken) return toDetail(byDsToken)
  }

  return null
}

export function listDatasetIds(): string[] {
  return readCatalog().map((record) => record.dataset_id)
}

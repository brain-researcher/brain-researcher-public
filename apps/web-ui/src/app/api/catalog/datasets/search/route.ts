import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'

import { searchCatalog } from '@/lib/server/dataset-catalog'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

const E2E_FIXTURE_HEADER = 'x-br-e2e'

const E2E_DATASET_CARD = {
  id: 'ds:openneuro:ds000001',
  name: 'Balloon Analog Risk-taking Task',
  description: 'E2E fixture dataset for PRD tests.',
  category: 'task',
  modalities: ['fmri'],
  acquisitions: [],
  subjects_count: 16,
  sessions_count: 1,
  access_type: 'open',
  license: 'CC0',
  source_repo: 'OpenNeuro',
  source_repo_id: 'ds000001',
  primary_url: 'https://openneuro.org/datasets/ds000001',
  center: undefined,
  consortium: undefined,
  tags: [],
  tasks: ['balloon analog risk task'],
  has_derivatives: false,
  preview_media: [],
  score: 1,
  size_human: undefined,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  onvoc: undefined,
} as const

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const asArray = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.filter(Boolean).map(String)
  if (value == null) return []
  return [String(value)]
}

function normalizeSourceRepo(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function canonicalizeDatasetId(props: Record<string, unknown>, item: any): string | null {
  const candidates = [
    props.dataset_id,
    props.source_repo_id,
    props.source_repo_dataset_id,
    props.id,
    item?.node_id,
    props.name,
    props.title,
  ]
    .filter((value) => typeof value === 'string' && value.trim().length > 0)
    .map((value) => (value as string).trim())

  const canonical = candidates.find((value) => value.startsWith('ds:'))
  if (canonical) return canonical

  const sourceRepo = (normalizeSourceRepo(props.source_repo ?? props.source) ?? '').toLowerCase()
  const sourceRepoId =
    (normalizeSourceRepo(props.source_repo_id) ??
      normalizeSourceRepo(props.dataset_id) ??
      normalizeSourceRepo(props.source_repo_dataset_id)) ??
    null

  if (sourceRepoId) {
    if (sourceRepo.includes('openneuro') || /^ds\d{6}$/i.test(sourceRepoId)) {
      return `ds:openneuro:${sourceRepoId}`
    }
    return `ds:manual:${sourceRepoId}`
  }

  return candidates[0] ?? null
}

async function searchBRKg(query: string | null, limit: number, offset: number) {
  if (!query) return null
  try {
    const effectiveLimit = clamp(limit + offset + 1, 1, 200)
    const base = resolveKgBaseUrl()
    const endpoints = ['/kg/api/search', '/api/search']

    let data: any = null
    let ok = false

    for (const endpoint of endpoints) {
      const searchResp = await fetch(`${base}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, node_types: ['Dataset'], limit: effectiveLimit }),
      })
      if (!searchResp.ok) continue
      data = await searchResp.json().catch(() => null)
      ok = true
      break
    }

    if (!ok) throw new Error('BR-KG search failed')
    const items = Array.isArray(data) ? data : data?.results || []
    const sliced = items.slice(offset, offset + limit)
    const hasMore = items.length > offset + limit || items.length >= effectiveLimit
    const total = hasMore ? offset + sliced.length + 1 : offset + sliced.length

    return {
      datasets: sliced.map((item: any) => {
        const props = item?.properties || {}
        const datasetId =
          canonicalizeDatasetId(props, item) ||
          props.dataset_id ||
          props.source_repo_id ||
          item?.node_id
        const name = props.name || props.title || datasetId
        const modalities = asArray(props.modalities ?? props.modality)
        const tasks = asArray(props.tasks ?? props.task)
        const subjects =
          props.subjects_count ?? props.n_subjects ?? props.subjects ?? props.n ?? undefined
        const source = props.source_repo || props.source || props.access_type || 'kg'
        const sourceRepoId = props.source_repo_id || props.dataset_id || datasetId
        const primaryUrl = props.primary_url || props.url || props.source_url || props.primaryUrl || undefined

        return {
          id: datasetId,
          name,
          description: props.description || props.summary || undefined,
          category: props.category || undefined,
          modalities,
          acquisitions: [],
          subjects_count: subjects,
          sessions_count: undefined,
          access_type: source,
          license: 'unknown',
          source_repo: source,
          source_repo_id: sourceRepoId,
          primary_url: primaryUrl || datasetId,
          center: props.center || undefined,
          consortium: props.consortium || undefined,
          tags: [],
          tasks,
          has_derivatives: Boolean(props.has_derivatives),
          preview_media: [],
          score: item?.score ?? undefined,
          created_at: undefined,
          updated_at: undefined,
        }
      }),
      total,
      limit,
      offset,
      has_more: hasMore,
      search_time_ms: 0,
      facets: {},
      last_updated: new Date().toISOString(),
    }
  } catch (error) {
    console.warn('[datasets/search] BR-KG search failed, falling back:', (error as Error)?.message)
    return null
  }
}

export async function GET(request: NextRequest) {
  if (process.env.NODE_ENV !== 'production' && request.headers.get(E2E_FIXTURE_HEADER) === '1') {
    const searchParams = request.nextUrl.searchParams
    const limit = clamp(Number(searchParams.get('limit')) || 24, 1, 100)
    const offset = Math.max(Number(searchParams.get('offset')) || 0, 0)
    const query = (searchParams.get('q') ?? searchParams.get('query') ?? '').toLowerCase()

    const matches =
      query.includes('ds000001') ||
      query.includes('balloon') ||
      query.includes('risk') ||
      query.includes('openneuro')

    const datasets = matches && offset === 0 ? [E2E_DATASET_CARD] : []
    const total = matches ? datasets.length : 0
    const hasMore = false

    return NextResponse.json({
      datasets: datasets.slice(0, limit),
      total,
      limit,
      offset,
      has_more: hasMore,
      search_time_ms: 0,
      facets: {},
      last_updated: new Date().toISOString(),
    })
  }

  const searchParams = request.nextUrl.searchParams
  const limit = clamp(Number(searchParams.get('limit')) || 24, 1, 100)
  const offset = Math.max(Number(searchParams.get('offset')) || 0, 0)
  const sort = (searchParams.get('sort') as 'relevance' | 'subjects' | 'updated') || 'relevance'
  const query = searchParams.get('q') ?? searchParams.get('query')

  const parseParam = (key: string) => {
    const value = searchParams.get(key)
    if (value == null) return undefined
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }

  const minSubjects = parseParam('min_subjects')
  const maxSubjects = parseParam('max_subjects')
  const ageMin = parseParam('age_min')
  const ageMax = parseParam('age_max')
  const trMin = parseParam('tr_min')
  const trMax = parseParam('tr_max')
  const voxelMin = parseParam('voxel_min')
  const voxelMax = parseParam('voxel_max')
  const trExact = parseParam('tr')
  const voxelExact = parseParam('voxel_mm') ?? parseParam('voxel')

  const numericFilters = {
    min_subjects: minSubjects,
    max_subjects: maxSubjects,
    age_min: ageMin,
    age_max: ageMax,
    tr_min: trExact ?? trMin,
    tr_max: trExact ?? trMax,
    voxel_min: voxelExact ?? voxelMin,
    voxel_max: voxelExact ?? voxelMax,
  }

  const params = {
    query,
    modalities: searchParams.getAll('modalities'),
    acquisitions: searchParams.getAll('acquisitions'),
    source_repo: searchParams.getAll('source_repo'),
    access_type: searchParams.getAll('access_type'),
    category: searchParams.getAll('category'),
    tags: searchParams.getAll('tags'),
    center: searchParams.getAll('center'),
    consortium: searchParams.getAll('consortium'),
    limit,
    offset,
    sort,
    ...numericFilters,
  }

  try {
    const result = searchCatalog(params)
    const hasNumericFilters = Object.values(numericFilters).some((value) => value != null)
    const shouldFallbackToBRKg = !hasNumericFilters && (result.total ?? 0) === 0
    if (shouldFallbackToBRKg) {
      const brKgResult = await searchBRKg(query, limit, offset)
      if (brKgResult && brKgResult.total > 0) {
        return NextResponse.json(brKgResult)
      }
    }

    return NextResponse.json(result)
  } catch (error) {
    console.error('Failed to search dataset catalog', error)
    return NextResponse.json({ error: 'Failed to load dataset catalog' }, { status: 500 })
  }
}

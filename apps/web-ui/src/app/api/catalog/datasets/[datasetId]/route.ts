import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'

import { getDataset } from '@/lib/server/dataset-catalog'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

interface Params {
  params: { datasetId: string }
}

const asArray = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.filter(Boolean).map(String)
  if (value == null) return []
  return [String(value)]
}

const parseCount = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function decodeDatasetId(datasetId: string): string {
  let decoded = datasetId.trim()
  for (let i = 0; i < 2; i += 1) {
    try {
      const next = decodeURIComponent(decoded).trim()
      if (!next || next === decoded) break
      decoded = next
    } catch {
      break
    }
  }
  return decoded
}

function normalizeDatasetQuery(datasetId: string) {
  const decoded = decodeDatasetId(datasetId)
  const candidates = [decoded]
  if (decoded.startsWith('ds:')) {
    const parts = decoded.split(':').filter(Boolean)
    const suffix = parts.at(-1)
    if (suffix && suffix !== decoded) candidates.push(suffix)
  }
  const openNeuroMatch = decoded.match(/ds\d{6}/i)
  if (openNeuroMatch && !candidates.includes(openNeuroMatch[0])) candidates.push(openNeuroMatch[0])
  return candidates
}

async function fetchBRKgDatasetDetail(datasetId: string) {
  const queries = normalizeDatasetQuery(datasetId)
  const desired = decodeDatasetId(datasetId).toLowerCase()
  const base = resolveKgBaseUrl()
  const endpoints = ['/kg/api/search', '/api/search']

  for (const query of queries) {
    for (const endpoint of endpoints) {
      try {
        const resp = await fetch(`${base}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, node_types: ['Dataset'], limit: 25 }),
        })
        if (!resp.ok) continue

        const data = await resp.json().catch(() => null)
        const items = Array.isArray(data) ? data : (data as any)?.results || []
        if (!Array.isArray(items) || items.length === 0) continue

        const pick = items
          .map((item: any) => {
            const props = item?.properties || {}
            const candidateId = String(
              props.dataset_id ||
                props.source_repo_id ||
                props.source_repo_dataset_id ||
                props.id ||
                item?.node_id ||
                '',
            ).trim()
            const normalizedId = candidateId.toLowerCase()
            const exact = normalizedId && normalizedId === desired
            const includes =
              normalizedId &&
              (desired.includes(normalizedId) || normalizedId.includes(desired))
            return { item, props, score: exact ? 100 : includes ? 50 : 0 }
          })
          .sort((a, b) => b.score - a.score)[0]

        const props = pick?.props || items[0]?.properties || {}
        const sourceRepo =
          props.source_repo || props.source || props.access_type || 'kg'
        const sourceRepoId =
          props.source_repo_id ||
          props.dataset_id ||
          props.source_repo_dataset_id ||
          decodeURIComponent(datasetId)

        const normalizedId = String(props.dataset_id || props.id || datasetId).trim()
        const canonicalId = normalizedId.startsWith('ds:')
          ? normalizedId
          : typeof sourceRepoId === 'string' && /^ds\d{6}$/i.test(sourceRepoId)
            ? `ds:openneuro:${sourceRepoId}`
            : `ds:manual:${sourceRepoId}`

        return {
          id: canonicalId,
          name: props.name || props.title || canonicalId,
          description: props.description || props.summary || undefined,
          category: props.category || undefined,
          modalities: asArray(props.modalities ?? props.modality),
          acquisitions: [],
          subjects_count: parseCount(
            props.subjects_count ?? props.n_subjects ?? props.subjects ?? props.n,
          ),
          sessions_count: parseCount(props.sessions_count),
          access_type: String(props.access_type || sourceRepo),
          license: String(props.license || 'unknown'),
          source_repo: String(sourceRepo),
          source_repo_id: typeof sourceRepoId === 'string' ? sourceRepoId : undefined,
          primary_url: String(
            props.primary_url || props.url || props.source_url || canonicalId,
          ),
          center: props.center || undefined,
          consortium: props.consortium || undefined,
          tags: [],
          tasks: asArray(props.tasks ?? props.task),
          has_derivatives: Boolean(props.has_derivatives),
          preview_media: [],
          score: typeof pick?.item?.score === 'number' ? pick.item.score : undefined,
          created_at: props.created_at || props.created || undefined,
          updated_at: props.updated_at || props.updated || undefined,
          species: asArray(props.species).length ? asArray(props.species) : ['human'],
          disease_flags: asArray(props.disease_flags ?? props.diseases ?? props.disease),
          search_blob: '',
        }
      } catch (error) {
        console.warn(
          '[datasets/detail] BR-KG lookup failed:',
          (error as Error)?.message,
        )
      }
    }
  }

  return null
}

export async function GET(_request: NextRequest, { params }: Params) {
  try {
    if (process.env.NODE_ENV !== 'production' && _request.headers.get('x-br-e2e') === '1') {
      const normalized = decodeDatasetId(params.datasetId).toLowerCase()
      if (normalized.includes('ds000001')) {
        return NextResponse.json({
          id: 'ds:openneuro:ds000001',
          name: 'Balloon Analog Risk-taking Task',
          description: 'E2E fixture dataset detail for PRD tests.',
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
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          species: ['human'],
          disease_flags: [],
          search_blob: '',
        })
      }
    }

    const candidates = normalizeDatasetQuery(params.datasetId)
    const dataset = candidates
      .map((candidate) => getDataset(candidate))
      .find((candidate) => candidate != null)

    if (!dataset) {
      const brKgDataset = await fetchBRKgDatasetDetail(candidates[0] ?? params.datasetId)
      if (brKgDataset) {
        return NextResponse.json(brKgDataset)
      }
      return NextResponse.json({ error: 'Dataset not found' }, { status: 404 })
    }
    return NextResponse.json(dataset)
  } catch (error) {
    console.error('Failed to load dataset detail', error)
    return NextResponse.json({ error: 'Failed to load dataset catalog' }, { status: 500 })
  }
}

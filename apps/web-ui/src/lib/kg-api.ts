import { serviceEndpoints } from '@/lib/service-endpoints'

const join = (path: string) =>
  path.startsWith('http') ? path : serviceEndpoints.kg(path)

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(join(path), {
    headers: { 'Content-Type': 'application/json' },
    method: 'GET',
    ...init,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`BR-KG ${path} ${res.status}`)
  return res.json() as Promise<T>
}

export type ConceptListItem = {
  id: string
  label: string
  category?: string
  counts: {
    statmaps: number
    coords: number
    timeseries: number
    datasets: number
    papers: number
    tasks?: number
    contrasts?: number
    tools?: number
    studies?: number
  }
}

export type ConceptsResponse = {
  items?: ConceptListItem[]
  concepts?: ConceptListItem[]
  counts?: {
    concepts?: number
  }
  next_cursor?: string | null
}

export type ConceptDetail = {
  id: string
  label: string
  definition?: string
  synonyms?: string[]
  parents: { id: string; label: string }[]
  children: { id: string; label: string }[]
}

export type EvidenceCounts = {
  statmaps: number
  coords: number
  timeseries: number
  datasets: number
  papers: number
  tasks?: number
  contrasts?: number
  tools?: number
  studies?: number
}

export type EvidenceGroups = {
  statmaps: StatMapEvidence[]
  coords: any[]
  timeseries: any[]
  datasets: any[]
  papers: any[]
  tasks?: any[]
  contrasts?: any[]
  tools?: any[]
  studies?: any[]
}

export type StatMapEvidence = {
  map_id: string
  space?: string
  atlas?: string
  contrast?: string
  url?: string
}

export type EvidenceResponse = {
  concept: { id: string }
  counts: EvidenceCounts
  groups: EvidenceGroups
  next_cursor: string | null
}

export type FetchConceptEvidenceParams = {
  types?: string[]
  limit?: number
  space?: string
  atlas?: string
  confidenceMin?: number
  verifiedOnly?: boolean
}

export async function fetchConcepts(params: { q?: string; limit?: number; category?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.category) qs.set('category', params.category)
  const query = qs.toString()
  const payload = await request<ConceptListItem[] | ConceptsResponse>(
    `/concepts${query ? `?${query}` : ''}`,
  )
  if (Array.isArray(payload)) {
    return payload
  }
  if (payload && Array.isArray(payload.items)) {
    return payload.items
  }
  if (payload && Array.isArray(payload.concepts)) {
    return payload.concepts
  }
  return []
}

export async function fetchConcept(id: string) {
  return request<ConceptDetail>(`/concept/${encodeURIComponent(id)}`)
}

export async function fetchConceptEvidence(
  id: string,
  paramsOrTypes?: string[] | FetchConceptEvidenceParams,
) {
  const params = Array.isArray(paramsOrTypes)
    ? { types: paramsOrTypes }
    : (paramsOrTypes ?? {})
  const qs = new URLSearchParams()
  if (params.types?.length) qs.set('types', params.types.join(','))
  if (params.limit !== undefined) qs.set('limit', String(params.limit))
  if (params.space) qs.set('space', params.space)
  if (params.atlas) qs.set('atlas', params.atlas)
  if (params.confidenceMin !== undefined) qs.set('confidence_min', String(params.confidenceMin))
  if (params.verifiedOnly !== undefined) qs.set('verified_only', String(params.verifiedOnly))
  return request<EvidenceResponse>(
    `/concept/${encodeURIComponent(id)}/evidence${qs.toString() ? `?${qs}` : ''}`,
  )
}

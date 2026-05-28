import { apiClient } from '@/lib/api'
import type { Dataset } from '@/types/dataset'
import type { DatasetCardResponse, DatasetSearchResponse, FacetValueResponse } from '@/types/datasets-search'

export const DATASET_CATEGORY_LABELS: ReadonlyArray<string> = [
  'Population & Lifespan Studies (Healthy)',
  'Clinical & Disease-Specific Cohorts',
  'Deep Phenotyping & Naturalistic Stimuli',
  'Animal & Connectomic Datasets',
  'Human Atlases & Genomics (Postmortem / In Vitro)',
  'Repositories, Meta-Analysis & Clinical Tools',
  'Simulation & Synthetic Data',
]

const CATEGORY_FALLBACK = 'Repositories, Meta-Analysis & Clinical Tools'

const CATEGORY_BY_SOURCE: Record<string, string> = {
  OpenNeuro: 'Repositories, Meta-Analysis & Clinical Tools',
  HCP: 'Population & Lifespan Studies (Healthy)',
  ABCD: 'Population & Lifespan Studies (Healthy)',
  ADNI: 'Clinical & Disease-Specific Cohorts',
  DANDI: 'Repositories, Meta-Analysis & Clinical Tools',
}

const CONTROLLED_MODALITIES = [
  'MRI',
  'fMRI',
  'sMRI',
  'dMRI',
  'DTI',
  'DWI',
  'EEG',
  'MEG',
  'iEEG',
  'ECoG',
  'PET',
  'Behavior',
  'Genomics',
  'EHR',
  'Simulation',
]

const DEFAULT_SOURCES = [
  'OpenNeuro',
  'HCP',
  'ABCD',
  'ADNI',
  'DANDI',
  'NITRC / INDI',
  'LONI',
  'NIMH Data Archive (NDA)',
  'Custom',
]

type DatasetFiltersInput = Partial<{
  search: string
  modality: string[]
  source: string[]
  category: string[]
  nSubjectsMin: number
  nSubjectsMax: number
  tasks: string[]
  sortBy: 'popularity' | 'nSubjects' | 'lastUpdated' | 'name'
  sortDirection: 'asc' | 'desc'
  limit: number
  offset: number
}>

const CLIENT_FILTER_KEYS: Array<keyof DatasetFiltersInput> = [
  'nSubjectsMin',
  'nSubjectsMax',
  'tasks',
]

const CLIENT_SORT_KEYS = new Set<DatasetFiltersInput['sortBy']>(['name', 'popularity'])

const DEFAULT_PAGE_SIZE = 24
const MAX_CLIENT_FETCH = 2000

const toDate = (value?: string | null): Date => {
  if (!value) return new Date()
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed
}

const deriveCategory = (card: DatasetCardResponse): string => {
  if (card.category) return card.category
  return CATEGORY_BY_SOURCE[card.source_repo] || CATEGORY_FALLBACK
}

const derivePopularity = (score?: number | null): number => {
  if (!score || Number.isNaN(score)) return 3
  const normalized = Math.round(score)
  return Math.max(1, Math.min(5, normalized))
}

const mapCardToDataset = (card: DatasetCardResponse): Dataset => ({
  id: card.id,
  name: card.name,
  description: card.description || '',
  source: card.source_repo,
  category: deriveCategory(card),
  modality: card.modalities || [],
  nSubjects: card.subjects_count ?? 0,
  nSessions: card.sessions_count ?? undefined,
  tasks: card.tasks || [],
  tags: card.tags || [],
  popularity: derivePopularity(card.score),
  size: card.size_human || '—',
  lastUpdated: toDate(card.updated_at || card.created_at),
  url: card.primary_url,
  thumbnail: card.preview_media?.[0]?.uri,
})

const needsClientFiltering = (filters?: DatasetFiltersInput): boolean => {
  if (!filters) return false
  return CLIENT_FILTER_KEYS.some((key) => Boolean(filters[key])) || CLIENT_SORT_KEYS.has(filters.sortBy ?? undefined)
}

const applyClientFiltering = (datasets: Dataset[], filters?: DatasetFiltersInput): Dataset[] => {
  if (!filters) return datasets
  let filtered = [...datasets]

  if (filters.nSubjectsMin != null) {
    filtered = filtered.filter((dataset) => dataset.nSubjects >= filters.nSubjectsMin!)
  }

  if (filters.nSubjectsMax != null) {
    filtered = filtered.filter((dataset) => dataset.nSubjects <= filters.nSubjectsMax!)
  }

  if (filters.tasks?.length) {
    const taskSet = new Set(filters.tasks.map((task) => task.toLowerCase()))
    filtered = filtered.filter((dataset) => dataset.tasks?.some((task) => taskSet.has(task.toLowerCase())))
  }

  return filtered
}

const applyClientSorting = (datasets: Dataset[], filters?: DatasetFiltersInput): Dataset[] => {
  if (!filters?.sortBy || !CLIENT_SORT_KEYS.has(filters.sortBy)) {
    return datasets
  }

  const sorted = [...datasets]
  sorted.sort((a, b) => {
    if (filters.sortBy === 'name') {
      return a.name.localeCompare(b.name)
    }
    if (filters.sortBy === 'popularity') {
      return b.popularity - a.popularity
    }
    return 0
  })

  if (filters.sortDirection === 'asc') {
    return sorted
  }
  return sorted.reverse()
}

const paginate = (datasets: Dataset[], offset: number, limit: number): Dataset[] => {
  const start = Math.max(offset, 0)
  const end = start + limit
  return datasets.slice(start, end)
}

type ApiSort = 'relevance' | 'subjects' | 'updated'

const mapSortToApi = (sortBy?: DatasetFiltersInput['sortBy']): ApiSort => {
  if (sortBy === 'nSubjects') return 'subjects'
  if (sortBy === 'lastUpdated') return 'updated'
  return 'relevance'
}

interface DatasetResult {
  datasets: Dataset[]
  total: number
  facets?: Record<string, FacetValueResponse[]>
}

const summarizeCategories = (datasets: Dataset[]): Record<string, FacetValueResponse[]> => {
  const counts = new Map<string, number>()
  datasets.forEach((dataset) => {
    const key = dataset.category || 'Uncategorized'
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return {
    category: Array.from(counts.entries()).map(([value, count]) => ({ value, count })),
  }
}

export async function getDatasets(filters?: DatasetFiltersInput): Promise<DatasetResult> {
  const limit = filters?.limit ?? DEFAULT_PAGE_SIZE
  const offset = filters?.offset ?? 0
  const requiresClientPass = needsClientFiltering(filters)

  if (requiresClientPass) {
    const bulk = await apiClient.getDatasets({
      limit: MAX_CLIENT_FETCH,
      offset: 0,
      search: filters?.search,
      modalities: filters?.modality,
      source_repo: filters?.source,
      category: filters?.category,
    })

    let datasets = bulk.datasets.map(mapCardToDataset)
    datasets = applyClientFiltering(datasets, filters)
    datasets = applyClientSorting(datasets, filters)

    const paged = paginate(datasets, offset, limit)
    return {
      datasets: paged,
      total: datasets.length,
      facets: summarizeCategories(datasets),
    }
  }

  const response = await apiClient.getDatasets({
    limit,
    offset,
    search: filters?.search,
    modalities: filters?.modality,
    source_repo: filters?.source,
    category: filters?.category,
    sort: mapSortToApi(filters?.sortBy),
  })

  if (!response?.datasets) {
    return { datasets: [], total: 0 }
  }

  return {
    datasets: response.datasets.map(mapCardToDataset),
    total: response.total,
    facets: response.facets,
  }
}

export function getFilterOptions() {
  return {
    modalities: [...CONTROLLED_MODALITIES],
    sources: [...DEFAULT_SOURCES],
    tasks: [] as string[],
    constructs: [] as string[],
    tags: [] as string[],
    categories: [...DATASET_CATEGORY_LABELS],
  }
}

// Dataset Card & Explorer integration helpers.

import { serviceEndpoints } from '@/lib/service-endpoints'

interface Dataset {
  id: string
  name: string
  source: 'OpenNeuro' | 'HCP' | 'ABCD' | 'Custom'
  modality: string[]
  n_subjects: number
  n_sessions?: number
  age_range?: { min: number; max: number }
  sex_distribution?: { male: number; female: number; other?: number }
  tasks?: string[]
  description?: string
  doi?: string
  authors?: string[]
  license?: string
  size_gb?: number
  bids_version?: string
  quality_score?: number
  created_date?: Date
  updated_date?: Date
  download_url?: string
  preview_images?: string[]
  metadata?: Record<string, any>
}

interface DatasetFilters {
  sources?: string[]
  modalities?: string[]
  subject_range?: { min: number; max: number }
  tasks?: string[]
  quality_score_min?: number
  has_derivatives?: boolean
  bids_compliant?: boolean
}

interface DatasetSearchResult {
  datasets: Dataset[]
  total_count: number
  page: number
  page_size: number
  facets: {
    sources: { value: string; count: number }[]
    modalities: { value: string; count: number }[]
    tasks: { value: string; count: number }[]
  }
}

interface DatasetStatistics {
  total_subjects: number
  total_sessions: number
  total_size_gb: number
  file_types: { type: string; count: number }[]
  scan_types: { type: string; count: number }[]
  average_quality_score: number
}

class DatasetIntegration {
  private baseUrl: string
  private cache: Map<string, any> = new Map()
  
  constructor(baseUrl: string = serviceEndpoints.orchestratorBase) {
    this.baseUrl = baseUrl
  }

  /**
   * Search datasets with filters
   */
  async searchDatasets(
    query?: string,
    filters?: DatasetFilters,
    page: number = 1,
    pageSize: number = 20,
    sort: 'name' | 'date' | 'size' | 'subjects' = 'name',
    order: 'asc' | 'desc' = 'asc'
  ): Promise<DatasetSearchResult> {
    const offset = Math.max(page - 1, 0) * pageSize
    const params = new URLSearchParams({
      limit: pageSize.toString(),
      offset: offset.toString(),
      sort:
        sort === 'subjects'
          ? 'subjects'
          : sort === 'date'
            ? 'updated'
            : 'relevance',
      order,
    })
    
    if (query) params.append('query', query)
    
    // Add filters
    if (filters) {
      if (filters.sources?.length) {
        filters.sources.forEach((value) => params.append('source_repo', value))
      }
      if (filters.modalities?.length) {
        filters.modalities.forEach((value) => params.append('modalities', value))
      }
    }
    
    const response = await fetch(`${this.baseUrl}/api/datasets?${params}`)
    
    if (!response.ok) {
      throw new Error(`Failed to search datasets: ${response.statusText}`)
    }

    const payload = await response.json()
    const datasets = Array.isArray(payload?.datasets)
      ? payload.datasets
      : Array.isArray(payload?.results)
        ? payload.results
        : []

    return {
      datasets,
      total_count:
        Number(payload?.total_count ?? payload?.total ?? datasets.length) || datasets.length,
      page,
      page_size: Number(payload?.page_size ?? payload?.limit ?? pageSize) || pageSize,
      facets:
        payload?.facets ?? {
          sources: [],
          modalities: [],
          tasks: [],
        },
    }
  }

  /**
   * Get dataset details
   */
  async getDataset(datasetId: string): Promise<Dataset> {
    // Check cache first
    const cacheKey = `dataset_${datasetId}`
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey)
    }
    
    const response = await fetch(`${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}`)
    
    if (!response.ok) {
      throw new Error(`Failed to fetch dataset: ${response.statusText}`)
    }
    
    const dataset = await response.json()
    
    // Cache for 5 minutes
    this.cache.set(cacheKey, dataset)
    setTimeout(() => this.cache.delete(cacheKey), 5 * 60 * 1000)
    
    return dataset
  }

  /**
   * Get dataset statistics
   */
  async getDatasetStatistics(datasetId: string): Promise<DatasetStatistics> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/statistics`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to fetch dataset statistics: ${response.statusText}`)
    }
    
    return await response.json()
  }

  /**
   * Get dataset preview
   */
  async getDatasetPreview(datasetId: string): Promise<any> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/preview`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to fetch dataset preview: ${response.statusText}`)
    }
    
    return await response.json()
  }

  /**
   * Download dataset
   */
  async downloadDataset(datasetId: string, format: 'bids' | 'nifti' | 'json' = 'bids'): Promise<void> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/download?format=${format}`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to download dataset: ${response.statusText}`)
    }
    
    // Get filename from headers or use default
    const contentDisposition = response.headers.get('content-disposition')
    const filename = contentDisposition
      ? contentDisposition.split('filename=')[1]?.replace(/"/g, '')
      : `dataset_${datasetId}.tar.gz`
    
    // Create download
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  /**
   * Get related datasets
   */
  async getRelatedDatasets(datasetId: string, limit: number = 5): Promise<Dataset[]> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/related?limit=${limit}`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to fetch related datasets: ${response.statusText}`)
    }
    
    const data = await response.json()
    return data.datasets
  }

  /**
   * Check dataset quality
   */
  async checkDatasetQuality(datasetId: string): Promise<any> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/quality`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to check dataset quality: ${response.statusText}`)
    }
    
    return await response.json()
  }

  /**
   * Get dataset citations
   */
  async getDatasetCitations(datasetId: string): Promise<any[]> {
    const response = await fetch(
      `${this.baseUrl}/api/datasets/${encodeURIComponent(datasetId)}/citations`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to fetch dataset citations: ${response.statusText}`)
    }
    
    const data = await response.json()
    return data.citations
  }

  /**
   * Load datasets from BR-KG
   */
  async loadFromBRKG(source: 'OpenNeuro' | 'HCP' | 'all' = 'all'): Promise<Dataset[]> {
    try {
      const filters =
        source === 'all'
          ? undefined
          : {
              sources: [source],
            }
      const result = await this.searchDatasets(undefined, filters, 1, 100)
      return result.datasets
    } catch (error) {
      console.warn('Failed to connect to BR-KG:', error)
      // Fallback to orchestrator datasets
      const result = await this.searchDatasets()
      return result.datasets
    }
  }
}

// React hooks for dataset integration
import { useState, useEffect, useCallback, useMemo } from 'react'

export function useDatasets(
  initialFilters?: DatasetFilters,
  pageSize: number = 20
) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [filters, setFilters] = useState<DatasetFilters>(initialFilters || {})
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState<'name' | 'date' | 'size' | 'subjects'>('name')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [facets, setFacets] = useState<any>(null)
  
  const integration = useMemo(() => new DatasetIntegration(), [])
  
  const loadDatasets = useCallback(async () => {
    setLoading(true)
    setError(null)
    
    try {
      const result = await integration.searchDatasets(
        searchQuery || undefined,
        filters,
        page,
        pageSize,
        sortBy,
        sortOrder
      )
      
      setDatasets(result.datasets)
      setTotalCount(result.total_count)
      setFacets(result.facets)
    } catch (error) {
      setError(error.message)
    } finally {
      setLoading(false)
    }
  }, [integration, searchQuery, filters, page, pageSize, sortBy, sortOrder])
  
  useEffect(() => {
    loadDatasets()
  }, [loadDatasets])
  
  const updateFilters = useCallback((newFilters: Partial<DatasetFilters>) => {
    setFilters(prev => ({ ...prev, ...newFilters }))
    setPage(1) // Reset to first page when filters change
  }, [])
  
  const clearFilters = useCallback(() => {
    setFilters({})
    setSearchQuery('')
    setPage(1)
  }, [])
  
  const totalPages = Math.ceil(totalCount / pageSize)
  
  return {
    datasets,
    loading,
    error,
    page,
    totalPages,
    totalCount,
    filters,
    searchQuery,
    sortBy,
    sortOrder,
    facets,
    setPage,
    setSearchQuery,
    setSortBy,
    setSortOrder,
    updateFilters,
    clearFilters,
    reload: loadDatasets
  }
}

export function useDataset(datasetId: string | null) {
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [statistics, setStatistics] = useState<DatasetStatistics | null>(null)
  const [related, setRelated] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const integration = useMemo(() => new DatasetIntegration(), [])
  
  const loadDataset = useCallback(async () => {
    if (!datasetId) return
    
    setLoading(true)
    setError(null)
    
    try {
      const [datasetData, stats, relatedDatasets] = await Promise.all([
        integration.getDataset(datasetId),
        integration.getDatasetStatistics(datasetId),
        integration.getRelatedDatasets(datasetId)
      ])
      
      setDataset(datasetData)
      setStatistics(stats)
      setRelated(relatedDatasets)
    } catch (error) {
      setError(error.message)
    } finally {
      setLoading(false)
    }
  }, [integration, datasetId])
  
  useEffect(() => {
    loadDataset()
  }, [loadDataset])
  
  const downloadDataset = useCallback(async (format?: 'bids' | 'nifti' | 'json') => {
    if (!datasetId) return
    
    try {
      await integration.downloadDataset(datasetId, format)
    } catch (error) {
      setError(error.message)
      throw error
    }
  }, [integration, datasetId])
  
  const checkQuality = useCallback(async () => {
    if (!datasetId) return null
    
    try {
      return await integration.checkDatasetQuality(datasetId)
    } catch (error) {
      setError(error.message)
      throw error
    }
  }, [integration, datasetId])
  
  return {
    dataset,
    statistics,
    related,
    loading,
    error,
    downloadDataset,
    checkQuality,
    reload: loadDataset
  }
}

export { DatasetIntegration }
export type { Dataset, DatasetFilters, DatasetSearchResult, DatasetStatistics }

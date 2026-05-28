import { KnowledgeGraph, BrainMapData } from '@/types/visualization'
import {
  resolveKgConceptEvidenceUrl,
  resolveKgEvidenceUrl,
  resolveKgGraphUrl,
} from './service-endpoints'

const buildProxyUrl = (path: string, params?: URLSearchParams): string => {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const qs = params?.toString()
  return `${normalized}${qs ? `?${qs}` : ''}`
}

const isExpectedVisualizationStatus = (status: number): boolean =>
  [401, 403, 404, 502, 503].includes(status)

const isExpectedVisualizationError = (error: unknown): boolean => {
  const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase()
  return (
    message.includes('failed to fetch') ||
    message.includes('networkerror') ||
    message.includes('network error') ||
    message.includes('fetch failed')
  )
}

/**
 * Fetch workflow/provenance graph for a specific run from the BR-KG service.
 * This replaces the mock `generateMockKnowledgeGraph` function.
 *
 * @param runId - The job/run ID to fetch the graph for
 * @returns Promise<KnowledgeGraph> - The workflow graph data
 */
export async function fetchWorkflowGraph(runId: string): Promise<KnowledgeGraph> {
  try {
    // Fetch graph data from BR-KG graph endpoint
    const params = new URLSearchParams({
      job_id: runId,
      limit: '100',
    })
    const url = resolveKgGraphUrl(params)
    const response = await fetch(url)

    if (!response.ok) {
      if (isExpectedVisualizationStatus(response.status)) {
        return {
          nodes: [],
          edges: [],
          metadata: {
            title: 'Workflow Graph',
            description: 'Graph service unavailable',
            timestamp: new Date(),
          },
        }
      }
      throw new Error(`Failed to fetch workflow graph: ${response.statusText}`)
    }

    const data = await response.json()

    // Transform Neo4j graph data to KnowledgeGraph format
    const nodes = (data.nodes || []).map((node: any) => ({
      id: node.id,
      type: node.type || 'unknown',
      label: node.label || node.id,
      description: node.properties?.description || '',
      metadata: node.properties || {},
      position: node.position || { x: 0, y: 0 },
      size: node.size,
      color: node.color
    }))

    const edges = (data.edges || []).map((edge: any) => ({
      id: edge.id || `${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: edge.type || 'related',
      label: edge.label || edge.type,
      weight: edge.properties?.weight || 1,
      metadata: edge.properties || {}
    }))

    return {
      nodes,
      edges,
      metadata: {
        title: data.metadata?.title || 'Workflow Graph',
        description: data.metadata?.description || '',
        timestamp: data.metadata?.timestamp ? new Date(data.metadata.timestamp) : new Date()
      }
    }
  } catch (error) {
    if (!isExpectedVisualizationError(error)) {
      console.warn('Workflow graph unavailable', error)
    }
    // Return empty graph on error
    return {
      nodes: [],
      edges: [],
      metadata: {
        title: 'Workflow Graph',
        description: 'Error loading graph data',
        timestamp: new Date()
      }
    }
  }
}

/**
 * Fetch brain maps/statistical maps for a specific run from the BR-KG service.
 * This replaces the mock `generateMockBrainMaps` function.
 *
 * @param runId - The job/run ID to fetch brain maps for
 * @returns Promise<BrainMapData[]> - Array of brain map data
 */
export async function fetchBrainMaps(runId: string): Promise<BrainMapData[]> {
  try {
    // Fetch evidence data from BR-KG evidence endpoint
    const params = new URLSearchParams({
      job_id: runId,
      types: 'statmaps,coords',
      limit: '50',
    })
    const url =
      typeof window !== 'undefined'
        ? buildProxyUrl('/api/kg/evidence', params)
        : resolveKgEvidenceUrl(params)
    const response = await fetch(url)

    if (!response.ok) {
      if (isExpectedVisualizationStatus(response.status)) {
        return []
      }
      throw new Error(`Failed to fetch brain maps: ${response.statusText}`)
    }

    const data = await response.json()
    const brainMaps: BrainMapData[] = []

    // Transform statmaps to BrainMapData format
    if (data.groups?.statmaps) {
      data.groups.statmaps.forEach((statmap: any) => {
        brainMaps.push({
          id: statmap.map_id || statmap.id,
          name: statmap.contrast || statmap.name || 'Statistical Map',
          type: 'statistical',
          imageUrl: statmap.thumbnail_url || statmap.url || '',
          niftiUrl: statmap.url || '',
          threshold: statmap.threshold || 0.001,
          colormap: statmap.colormap || 'hot',
          coordinates: statmap.peak_coords ? {
            x: statmap.peak_coords.x || 0,
            y: statmap.peak_coords.y || 0,
            z: statmap.peak_coords.z || 0
          } : { x: 0, y: 0, z: 0 },
          peaks: statmap.peaks || [],
          metadata: {
            analysis: statmap.analysis_type || 'GLM',
            contrast: statmap.contrast || '',
            subjects: statmap.n_subjects || 0,
            corrected: statmap.correction_method || 'FWE',
            software: statmap.software || 'unknown',
            space: statmap.space || 'MNI152',
            atlas: statmap.atlas || ''
          }
        })
      })
    }

    // Transform coordinate data to brain map peaks if available
    if (data.groups?.coords && data.groups.coords.length > 0) {
      const coordMap: BrainMapData = {
        id: `coords-${runId}`,
        name: 'Activation Peaks',
        type: 'coordinate' as any,
        imageUrl: '',
        threshold: 0.001,
        colormap: 'hot',
        coordinates: data.groups.coords[0] ? {
          x: data.groups.coords[0].x || 0,
          y: data.groups.coords[0].y || 0,
          z: data.groups.coords[0].z || 0
        } : { x: 0, y: 0, z: 0 },
        peaks: data.groups.coords.map((coord: any) => ({
          x: coord.x,
          y: coord.y,
          z: coord.z,
          value: coord.value || coord.z_score || 0,
          region: coord.region || coord.label || 'Unknown'
        })),
        metadata: {
          analysis: 'Coordinates',
          subjects: 0,
          software: 'unknown'
        }
      }
      brainMaps.push(coordMap)
    }

    return brainMaps
  } catch (error) {
    if (!isExpectedVisualizationError(error)) {
      console.warn('Brain maps unavailable', error)
    }
    // Return empty array on error
    return []
  }
}

/**
 * Fetch concept-specific brain maps from BR-KG.
 *
 * @param conceptId - The ONVOC concept ID
 * @param options - Optional filters for types, space, atlas
 * @returns Promise<BrainMapData[]> - Array of brain map data
 */
export async function fetchConceptBrainMaps(
  conceptId: string,
  options?: { types?: string; space?: string; atlas?: string }
): Promise<BrainMapData[]> {
  try {
    const params = new URLSearchParams({ limit: '50' })
    if (options?.types) params.set('types', options.types)
    if (options?.space) params.set('space', options.space)
    if (options?.atlas) params.set('atlas', options.atlas)

    const url =
      typeof window !== 'undefined'
        ? buildProxyUrl(`/api/kg/concept/${encodeURIComponent(conceptId)}/evidence`, params)
        : resolveKgConceptEvidenceUrl(conceptId, params)
    const response = await fetch(url)

    if (!response.ok) {
      if (isExpectedVisualizationStatus(response.status)) {
        return []
      }
      throw new Error(`Failed to fetch concept brain maps: ${response.statusText}`)
    }

    const data = await response.json()
    const brainMaps: BrainMapData[] = []

    // Transform statmaps
    if (data.groups?.statmaps) {
      data.groups.statmaps.forEach((statmap: any) => {
        brainMaps.push({
          id: statmap.map_id || statmap.id,
          name: statmap.contrast || statmap.name || 'Statistical Map',
          type: 'statistical',
          imageUrl: statmap.thumbnail_url || statmap.url || '',
          niftiUrl: statmap.url || '',
          threshold: statmap.threshold || 0.001,
          colormap: statmap.colormap || 'hot',
          coordinates: statmap.peak_coords || { x: 0, y: 0, z: 0 },
          peaks: statmap.peaks || [],
          metadata: {
            analysis: statmap.analysis_type || 'GLM',
            contrast: statmap.contrast || '',
            subjects: statmap.n_subjects || 0,
            corrected: statmap.correction_method || 'FWE',
            software: statmap.software || 'unknown',
            space: statmap.space || 'MNI152',
            atlas: statmap.atlas || ''
          }
        })
      })
    }

    return brainMaps
  } catch (error) {
    if (!isExpectedVisualizationError(error)) {
      console.warn('Concept brain maps unavailable', error)
    }
    return []
  }
}

export interface KnowledgeGraphNode {
  id: string
  type: 'dataset' | 'analysis' | 'result' | 'tool' | 'parameter' | 'citation'
  label: string
  description?: string
  metadata?: Record<string, any>
  position?: { x: number; y: number }
  size?: number
  color?: string
}

export interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  type: 'uses' | 'generates' | 'cites' | 'configures' | 'derives_from'
  label?: string
  weight?: number
  metadata?: Record<string, any>
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  metadata?: {
    title?: string
    description?: string
    timestamp?: Date
  }
}

export interface BrainMapData {
  id: string
  name: string
  type: 'statistical' | 'connectivity' | 'parcellation' | 'overlay'
  imageUrl: string
  niftiUrl?: string
  threshold?: number
  colormap?: string
  coordinates?: {
    x: number
    y: number
    z: number
  }
  slices?: {
    axial: string[]
    sagittal: string[]
    coronal: string[]
  }
  peaks?: Array<{
    x: number
    y: number
    z: number
    value: number
    label?: string
    region?: string
  }>
  metadata?: Record<string, any>
}

export interface VisualizationConfig {
  showKnowledgeGraph: boolean
  showBrainMap: boolean
  brainMapView: '3d' | 'slices' | 'glass'
  knowledgeGraphLayout: 'force' | 'hierarchical' | 'circular'
  colorScheme: 'default' | 'viridis' | 'plasma' | 'cool'
}
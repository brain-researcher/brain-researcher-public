export interface Dataset {
  id: string
  name: string
  description: string
  source: string
  modality: string[]
  category?: string
  nSubjects: number
  nSessions?: number
  tasks?: string[]
  constructs?: string[]
  tr?: number // in seconds
  spatialResolution?: string // e.g., "2x2x2mm"
  fieldStrength?: string // e.g., "3T"
  tags: string[]
  popularity: number // 1-5 stars
  size: string // e.g., "2.3GB"
  lastUpdated: Date
  doi?: string
  url?: string
  readme?: string
  bidsTree?: BidsNode[]
  contrasts?: Contrast[]
  demographics?: Demographics
  thumbnail?: string
  onvoc?: { ids: string[]; labels?: string[] }
}

export interface BidsNode {
  name: string
  type: 'folder' | 'file'
  path: string
  size?: number
  children?: BidsNode[]
}

export interface Contrast {
  name: string
  description: string
  conditions: string[]
  type: 'T' | 'F'
}

export interface Demographics {
  ageRange: [number, number]
  meanAge?: number
  genderDistribution?: {
    male: number
    female: number
    other?: number
  }
  handedness?: {
    right: number
    left: number
    ambidextrous?: number
  }
}

export interface DatasetFilters {
  search?: string
  modality?: string[]
  source?: string[]
  category?: string[]
  nSubjectsMin?: number
  nSubjectsMax?: number
  trMin?: number
  trMax?: number
  tasks?: string[]
  constructs?: string[]
  tags?: string[]
}

export interface DatasetSort {
  field: 'popularity' | 'nSubjects' | 'lastUpdated' | 'name' | 'size'
  direction: 'asc' | 'desc'
}

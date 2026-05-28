import {
  formatFileSize,
  formatDuration,
  filterItems,
  sortItems,
  paginateItems,
  getUniqueValues,
  getAnalysisStats,
  GalleryItem,
  FilterState
} from '../gallery-utils'

// Mock data
const mockItems: GalleryItem[] = [
  {
    id: '1',
    name: 'Brain Map Alpha',
    description: 'First brain map',
    type: 'brain-map',
    thumbnail: '/thumb1.jpg',
    fullUrl: '/brain1.nii.gz',
    fileSize: 1048576, // 1 MB
    mimeType: 'application/x-nifti',
    created: new Date('2024-01-01'),
    modified: new Date('2024-01-02'),
    analysis: {
      type: 'GLM',
      pipeline: 'fMRIPrep',
      duration: 300,
      status: 'completed'
    },
    metadata: {
      dimensions: [64, 64, 30],
      voxelSize: [3, 3, 3],
      format: 'NIfTI'
    },
    tags: ['contrast', 'task-faces'],
    annotations: 'Main effect of faces vs baseline'
  },
  {
    id: '2',
    name: 'Results Beta',
    description: 'Statistical results',
    type: 'table',
    thumbnail: '/thumb2.jpg',
    fullUrl: '/results.csv',
    fileSize: 51200, // 50 KB
    mimeType: 'text/csv',
    created: new Date('2024-01-03'),
    modified: new Date('2024-01-04'),
    analysis: {
      type: 'Statistical',
      pipeline: 'Custom',
      duration: 60,
      status: 'completed'
    },
    metadata: {
      rows: 1000,
      columns: 5,
      format: 'CSV'
    },
    tags: ['statistics', 'peaks']
  },
  {
    id: '3',
    name: 'Graph Charlie',
    description: 'Processing graph',
    type: 'graph',
    thumbnail: '/thumb3.jpg',
    fullUrl: '/graph.png',
    fileSize: 204800, // 200 KB
    mimeType: 'image/png',
    created: new Date('2024-01-05'),
    modified: new Date('2024-01-05'),
    analysis: {
      type: 'Visualization',
      pipeline: 'Matplotlib',
      duration: 120,
      status: 'processing'
    },
    metadata: {
      dimensions: { width: 800, height: 600 },
      format: 'PNG'
    },
    tags: ['visualization', 'timeseries']
  }
]

describe('gallery-utils', () => {
  describe('formatFileSize', () => {
    it('formats bytes correctly', () => {
      expect(formatFileSize(0)).toBe('0 B')
      expect(formatFileSize(1024)).toBe('1.00 KB')
      expect(formatFileSize(1048576)).toBe('1.00 MB')
      expect(formatFileSize(1073741824)).toBe('1.00 GB')
      expect(formatFileSize(1099511627776)).toBe('1.00 TB')
    })

    it('handles decimal places correctly', () => {
      expect(formatFileSize(1536)).toBe('1.50 KB')
      expect(formatFileSize(1572864)).toBe('1.50 MB')
    })
  })

  describe('formatDuration', () => {
    it('formats seconds correctly', () => {
      expect(formatDuration(30)).toBe('30s')
      expect(formatDuration(90)).toBe('1m 30s')
      expect(formatDuration(3660)).toBe('1h 1m')
      expect(formatDuration(7200)).toBe('2h 0m')
    })

    it('handles edge cases', () => {
      expect(formatDuration(0)).toBe('0s')
      expect(formatDuration(60)).toBe('1m 0s')
      expect(formatDuration(3600)).toBe('1h 0m')
    })
  })

  describe('filterItems', () => {
    it('filters by type', () => {
      const filters: FilterState = {
        types: ['brain-map'],
        dateRange: undefined,
        tags: undefined,
        search: undefined,
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].type).toBe('brain-map')
    })

    it('filters by multiple types', () => {
      const filters: FilterState = {
        types: ['brain-map', 'table'],
        dateRange: undefined,
        tags: undefined,
        search: undefined,
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(2)
      expect(result.map(item => item.type)).toContain('brain-map')
      expect(result.map(item => item.type)).toContain('table')
    })

    it('filters by date range', () => {
      const filters: FilterState = {
        types: [],
        dateRange: [new Date('2024-01-02'), new Date('2024-01-04')],
        tags: undefined,
        search: undefined,
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].id).toBe('2')
    })

    it('filters by tags', () => {
      const filters: FilterState = {
        types: [],
        dateRange: undefined,
        tags: ['contrast'],
        search: undefined,
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].tags).toContain('contrast')
    })

    it('filters by analysis type', () => {
      const filters: FilterState = {
        types: [],
        dateRange: undefined,
        tags: undefined,
        search: undefined,
        analysisTypes: ['GLM']
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].analysis.type).toBe('GLM')
    })

    it('filters by search term', () => {
      const filters: FilterState = {
        types: [],
        dateRange: undefined,
        tags: undefined,
        search: 'alpha',
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].name.toLowerCase()).toContain('alpha')
    })

    it('applies multiple filters', () => {
      const filters: FilterState = {
        types: ['brain-map', 'table'],
        dateRange: undefined,
        tags: undefined,
        search: 'brain',
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(1)
      expect(result[0].type).toBe('brain-map')
      expect(result[0].name.toLowerCase()).toContain('alpha')
    })

    it('returns empty array when no matches', () => {
      const filters: FilterState = {
        types: [],
        dateRange: undefined,
        tags: undefined,
        search: 'nonexistent',
        analysisTypes: undefined
      }
      
      const result = filterItems(mockItems, filters)
      expect(result).toHaveLength(0)
    })
  })

  describe('sortItems', () => {
    it('sorts by name ascending', () => {
      const result = sortItems(mockItems, 'name', 'asc')
      expect(result[0].name).toBe('Brain Map Alpha')
      expect(result[1].name).toBe('Graph Charlie')
      expect(result[2].name).toBe('Results Beta')
    })

    it('sorts by name descending', () => {
      const result = sortItems(mockItems, 'name', 'desc')
      expect(result[0].name).toBe('Results Beta')
      expect(result[1].name).toBe('Graph Charlie')
      expect(result[2].name).toBe('Brain Map Alpha')
    })

    it('sorts by date ascending', () => {
      const result = sortItems(mockItems, 'date', 'asc')
      expect(result[0].id).toBe('1') // 2024-01-01
      expect(result[1].id).toBe('2') // 2024-01-03
      expect(result[2].id).toBe('3') // 2024-01-05
    })

    it('sorts by date descending', () => {
      const result = sortItems(mockItems, 'date', 'desc')
      expect(result[0].id).toBe('3') // 2024-01-05
      expect(result[1].id).toBe('2') // 2024-01-03
      expect(result[2].id).toBe('1') // 2024-01-01
    })

    it('sorts by size ascending', () => {
      const result = sortItems(mockItems, 'size', 'asc')
      expect(result[0].fileSize).toBe(51200)   // 50 KB
      expect(result[1].fileSize).toBe(204800)  // 200 KB
      expect(result[2].fileSize).toBe(1048576) // 1 MB
    })

    it('sorts by type', () => {
      const result = sortItems(mockItems, 'type', 'asc')
      expect(result[0].type).toBe('brain-map')
      expect(result[1].type).toBe('graph')
      expect(result[2].type).toBe('table')
    })

    it('does not mutate original array', () => {
      const original = [...mockItems]
      sortItems(mockItems, 'name', 'asc')
      expect(mockItems).toEqual(original)
    })
  })

  describe('paginateItems', () => {
    it('paginates items correctly', () => {
      const result = paginateItems(mockItems, 1, 2)
      
      expect(result.items).toHaveLength(2)
      expect(result.totalPages).toBe(2)
      expect(result.hasNext).toBe(true)
      expect(result.hasPrev).toBe(false)
    })

    it('handles last page correctly', () => {
      const result = paginateItems(mockItems, 2, 2)
      
      expect(result.items).toHaveLength(1)
      expect(result.totalPages).toBe(2)
      expect(result.hasNext).toBe(false)
      expect(result.hasPrev).toBe(true)
    })

    it('handles single page', () => {
      const result = paginateItems(mockItems, 1, 10)
      
      expect(result.items).toHaveLength(3)
      expect(result.totalPages).toBe(1)
      expect(result.hasNext).toBe(false)
      expect(result.hasPrev).toBe(false)
    })

    it('handles empty items', () => {
      const result = paginateItems([], 1, 10)
      
      expect(result.items).toHaveLength(0)
      expect(result.totalPages).toBe(0)
      expect(result.hasNext).toBe(false)
      expect(result.hasPrev).toBe(false)
    })
  })

  describe('getUniqueValues', () => {
    it('gets unique types', () => {
      const result = getUniqueValues(mockItems, 'type')
      expect(result).toEqual(['brain-map', 'graph', 'table'])
    })

    it('gets unique tags (flattened)', () => {
      const result = getUniqueValues(mockItems, 'tags')
      expect(result).toEqual([
        'contrast', 'peaks', 'statistics', 
        'task-faces', 'timeseries', 'visualization'
      ])
    })

    it('handles string fields', () => {
      const result = getUniqueValues(mockItems, 'mimeType')
      expect(result).toEqual([
        'application/x-nifti', 
        'image/png', 
        'text/csv'
      ])
    })
  })

  describe('getAnalysisStats', () => {
    it('calculates statistics correctly', () => {
      const stats = getAnalysisStats(mockItems)
      
      expect(stats.totalItems).toBe(3)
      expect(stats.totalSize).toBe(1048576 + 51200 + 204800)
      expect(stats.totalDuration).toBe(300 + 60 + 120)
      expect(stats.avgDuration).toBe((300 + 60 + 120) / 3)
      
      expect(stats.typeBreakdown).toEqual({
        'brain-map': 1,
        'table': 1,
        'graph': 1
      })
      
      expect(stats.statusBreakdown).toEqual({
        'completed': 2,
        'processing': 1
      })
      
      expect(stats.analysisTypeBreakdown).toEqual({
        'GLM': 1,
        'Statistical': 1,
        'Visualization': 1
      })
    })

    it('handles empty items', () => {
      const stats = getAnalysisStats([])
      
      expect(stats.totalItems).toBe(0)
      expect(stats.totalSize).toBe(0)
      expect(stats.totalDuration).toBe(0)
      expect(stats.avgDuration).toBe(0)
      expect(stats.typeBreakdown).toEqual({})
      expect(stats.statusBreakdown).toEqual({})
      expect(stats.analysisTypeBreakdown).toEqual({})
    })
  })

  // Note: downloadItemsAsZip, exportItemsAsCSV, generateShareLink, and copyItemsToClipboard
  // would require more complex mocking of DOM APIs, file APIs, and clipboard APIs
  // These would typically be tested in integration or E2E tests

  describe('Edge Cases', () => {
    it('handles items with missing optional fields', () => {
      const minimalItem: GalleryItem = {
        id: '4',
        name: 'Minimal Item',
        type: 'metadata',
        thumbnail: '/thumb.jpg',
        fullUrl: '/file.json',
        fileSize: 1024,
        mimeType: 'application/json',
        created: new Date('2024-01-01'),
        modified: new Date('2024-01-01'),
        analysis: {
          type: 'Basic',
          pipeline: 'None',
          duration: 0,
          status: 'completed'
        },
        metadata: {},
        tags: []
      }

      const filters: FilterState = {
        types: [],
        search: 'minimal'
      }

      const result = filterItems([minimalItem], filters)
      expect(result).toHaveLength(1)
    })

    it('handles items with null/undefined values gracefully', () => {
      const itemWithNulls = {
        ...mockItems[0],
        description: undefined,
        annotations: undefined,
        tags: []
      }

      const filters: FilterState = {
        types: [],
        search: 'alpha'
      }

      const result = filterItems([itemWithNulls], filters)
      expect(result).toHaveLength(1)
    })
  })
})
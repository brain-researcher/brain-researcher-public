import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { makeJsonResponse } from '../helpers/fetch-mocks'

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent.test',
}))

// Mock fetch globally
const mockFetch = vi.fn()
global.fetch = mockFetch

// Helper to create mock NextRequest
const createMockRequest = (url: string, options: RequestInit = {}) => {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: Knowledge Graph Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  describe('GET /api/kg/pipelines', () => {
    it('should fetch pipelines from BR-KG successfully', async () => {
      const mockPipelineData = {
        results: [
          {
            id: 'fmriprep',
            name: 'fMRIPrep',
            ops: ['preprocessing', 'motion_correction'],
            preferred_families: ['fsl', 'afni'],
            datasets: ['openneuro'],
          },
          {
            id: 'qsiprep',
            name: 'QSIPrep',
            ops: ['dmri_preprocessing'],
            preferred_families: ['mrtrix', 'fsl'],
            datasets: ['hcp'],
          },
        ],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockPipelineData, 200))

      const { GET } = await import('@/app/api/kg/pipelines/route')
      const req = createMockRequest('http://test/api/kg/pipelines')
      const res = await GET(req)

      expect(res.status).toBe(200)
      const data = await res.json()
      expect(data.pipelines).toHaveLength(2)
      expect(data.pipelines[0].id).toBe('fmriprep')
      expect(data.pipelines[0].ops).toContain('preprocessing')
    })

    it('should handle BR-KG service errors', async () => {
      mockFetch.mockResolvedValueOnce(makeJsonResponse({}, 503))

      const { GET } = await import('@/app/api/kg/pipelines/route')
      const req = createMockRequest('http://test/api/kg/pipelines')
      const res = await GET(req)

      expect(res.status).toBe(503)
      const data = await res.json()
      expect(data.error).toContain('knowledge graph')
    })

    it('should handle timeout errors', async () => {
      mockFetch.mockImplementationOnce(() => {
        return new Promise((_, reject) => {
          setTimeout(() => reject(new DOMException('Aborted', 'AbortError')), 100)
        })
      })

      const { GET } = await import('@/app/api/kg/pipelines/route')
      const req = createMockRequest('http://test/api/kg/pipelines')
      const res = await GET(req)

      expect(res.status).toBe(504)
      const data = await res.json()
      expect(data.error).toContain('timed out')
    })

    it('should transform Cypher response to expected format', async () => {
      const mockCypherData = {
        data: [
          {
            id: 'pipeline1',
            name: 'Pipeline 1',
            ops: ['op1', null, 'op2'],
            preferred_families: ['family1'],
            datasets: [],
          },
        ],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockCypherData, 200))

      const { GET } = await import('@/app/api/kg/pipelines/route')
      const req = createMockRequest('http://test/api/kg/pipelines')
      const res = await GET(req)

      const data = await res.json()
      expect(data.pipelines[0].ops).toEqual(['op1', 'op2']) // null filtered out
    })
  })

  describe('GET /api/kg/tools', () => {
    it('should proxy tools request to Agent debug endpoint', async () => {
      const mockToolsData = {
        families: [
          {
            family_id: 'fsl',
            tools: [
              { tool_id: 'bet', is_promoted: true, runtime: 'singularity' },
            ],
            kg_tool_count: 5,
          },
        ],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockToolsData, 200))

      const { GET } = await import('@/app/api/kg/tools/route')
      const req = createMockRequest(
        'http://test/api/kg/tools?intent=skull_stripping&pipeline=fmriprep'
      )
      const res = await GET(req)

      expect(res.status).toBe(200)
      const data = await res.json()
      expect(data.families).toBeDefined()
      expect(data.families[0].family_id).toBe('fsl')

      // Verify fetch was called with correct URL
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/agent/debug/kg/tools'),
        expect.any(Object)
      )
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('http://agent.test'),
        expect.any(Object)
      )
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('intent=skull_stripping'),
        expect.any(Object)
      )
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('pipeline=fmriprep'),
        expect.any(Object)
      )
    })

    it('should apply default per_family limit of 5', async () => {
      mockFetch.mockResolvedValueOnce(makeJsonResponse({ families: [] }, 200))

      const { GET } = await import('@/app/api/kg/tools/route')
      const req = createMockRequest('http://test/api/kg/tools?intent=preprocessing')
      await GET(req)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('per_family=5'),
        expect.any(Object)
      )
    })

    it('should return 400 if intent parameter is missing', async () => {
      const { GET } = await import('@/app/api/kg/tools/route')
      const req = createMockRequest('http://test/api/kg/tools')
      const res = await GET(req)

      expect(res.status).toBe(400)
      const data = await res.json()
      expect(data.error).toContain('intent')
    })

    it('should handle Agent service errors', async () => {
      mockFetch.mockResolvedValueOnce(makeJsonResponse({}, 500))

      const { GET } = await import('@/app/api/kg/tools/route')
      const req = createMockRequest('http://test/api/kg/tools?intent=test')
      const res = await GET(req)

      expect(res.status).toBe(500)
      const data = await res.json()
      expect(data.error).toBeDefined()
    })
  })

  describe('POST /api/plan', () => {
    it('should proxy plan request to Agent planner', async () => {
      const mockPlanData = {
        chosen_tool: 'fsl_bet',
        pipeline: 'fmriprep',
        steps: [{ tool: 'bet', params: {} }],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockPlanData, 200))

      const { POST } = await import('@/app/api/plan/route')
      const req = createMockRequest('http://test/api/plan', {
        method: 'POST',
        body: JSON.stringify({ pipeline: 'fmriprep', modality: ['bold'] }),
        headers: { 'Content-Type': 'application/json' },
      })
      const res = await POST(req)

      expect(res.status).toBe(200)
      const data = await res.json()
      expect(data.chosen_tool).toBe('fsl_bet')
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('http://agent.test/agent/plan'),
        expect.objectContaining({ method: 'POST' })
      )
    })

    it('should inject debug_selection when requested via query param', async () => {
      const mockPlanData = {
        chosen_tool: 'fsl_bet',
        selection_reasons: 'Preferred tool for this operation',
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockPlanData, 200))

      const { POST } = await import('@/app/api/plan/route')
      const req = createMockRequest('http://test/api/plan?debug_selection=true', {
        method: 'POST',
        body: JSON.stringify({ pipeline: 'fmriprep' }),
        headers: { 'Content-Type': 'application/json' },
      })
      await POST(req)

      // Verify debug_selection was added to body
      const fetchCall = mockFetch.mock.calls[0]
      const bodyStr = fetchCall[1].body
      const body = JSON.parse(bodyStr)
      expect(body.debug_selection).toBe(true)
    })

    it('should return 400 for invalid JSON body', async () => {
      const { POST } = await import('@/app/api/plan/route')
      const req = createMockRequest('http://test/api/plan', {
        method: 'POST',
        body: 'invalid json',
        headers: { 'Content-Type': 'application/json' },
      })
      const res = await POST(req)

      expect(res.status).toBe(400)
      const data = await res.json()
      expect(data.error).toContain('Invalid JSON')
    })

    it('should handle plan generation errors with details', async () => {
      const errorDetails = { error: 'Invalid pipeline', details: 'Pipeline not found' }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(errorDetails, 404))

      const { POST } = await import('@/app/api/plan/route')
      const req = createMockRequest('http://test/api/plan', {
        method: 'POST',
        body: JSON.stringify({ pipeline: 'invalid' }),
        headers: { 'Content-Type': 'application/json' },
      })
      const res = await POST(req)

      expect(res.status).toBe(404)
      const data = await res.json()
      expect(data.error).toBe('Plan generation failed')
      expect(data.details).toBeDefined()
    })

    it('should handle timeout with 15s limit', async () => {
      mockFetch.mockImplementationOnce(() => {
        return new Promise((_, reject) => {
          setTimeout(() => reject(new DOMException('Aborted', 'AbortError')), 100)
        })
      })

      const { POST } = await import('@/app/api/plan/route')
      const req = createMockRequest('http://test/api/plan', {
        method: 'POST',
        body: JSON.stringify({ pipeline: 'test' }),
        headers: { 'Content-Type': 'application/json' },
      })
      const res = await POST(req)

      expect(res.status).toBe(504)
      const data = await res.json()
      expect(data.error).toContain('timed out')
    })
  })

  describe('GET /api/kg/search', () => {
    it('should search operations and synonyms', async () => {
      const mockSearchData = {
        results: [
          {
            node_id: 'skull_stripping',
            properties: {
              name: 'Skull Stripping',
              description: 'Remove skull from brain image',
            },
          },
        ],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockSearchData, 200))

      const { GET } = await import('@/app/api/kg/search/route')
      const req = createMockRequest('http://test/api/kg/search?q=skull')
      const res = await GET(req)

      expect(res.status).toBe(200)
      const data = await res.json()
      expect(data.operations).toHaveLength(1)
      expect(data.synonyms).toHaveLength(0)
      expect(data.operations[0].id).toBe('skull_stripping')
    })

    it('should return 400 if query parameter is missing', async () => {
      const { GET } = await import('@/app/api/kg/search/route')
      const req = createMockRequest('http://test/api/kg/search')
      const res = await GET(req)

      expect(res.status).toBe(400)
      const data = await res.json()
      expect(data.error).toContain('q')
    })

    it('should apply custom limit parameter', async () => {
      mockFetch.mockResolvedValueOnce(
        makeJsonResponse({ results: [{ operations: [], synonyms: [] }] }, 200),
      )

      const { GET } = await import('@/app/api/kg/search/route')
      const req = createMockRequest('http://test/api/kg/search?q=test&limit=10')
      await GET(req)

      // Verify fetch was called with Cypher query containing limit parameter
      const fetchCall = mockFetch.mock.calls[0]
      const bodyStr = fetchCall[1].body
      const body = JSON.parse(bodyStr)
      expect(body.limit).toBe(10)
    })

    it('should filter out null synonyms', async () => {
      const mockData = {
        results: [
          { node_id: '', properties: { name: '', description: '' } },
          {
            node_id: 'op1',
            properties: { name: 'Op 1' },
          },
        ],
      }

      mockFetch.mockResolvedValueOnce(makeJsonResponse(mockData, 200))

      const { GET } = await import('@/app/api/kg/search/route')
      const req = createMockRequest('http://test/api/kg/search?q=test')
      const res = await GET(req)

      const data = await res.json()
      expect(data.operations).toHaveLength(1)
      expect(data.operations[0].name).toBe('Op 1')
    })

    it('should handle search errors', async () => {
      mockFetch.mockResolvedValueOnce(makeJsonResponse({}, 500))

      const { GET } = await import('@/app/api/kg/search/route')
      const req = createMockRequest('http://test/api/kg/search?q=test')
      const res = await GET(req)

      expect(res.status).toBe(500)
      const data = await res.json()
      expect(data.error).toBe('Search failed')
    })
  })
})

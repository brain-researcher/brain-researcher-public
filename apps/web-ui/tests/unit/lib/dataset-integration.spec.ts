import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockFetch = vi.fn()
global.fetch = mockFetch

describe('DatasetIntegration.loadFromBRKG', () => {
  beforeEach(() => {
    vi.resetModules()
    mockFetch.mockReset()
  })

  it('reuses canonical dataset search with source filters', async () => {
    const { DatasetIntegration } = await import('@/lib/dataset-integration')
    const integration = new DatasetIntegration()
    const searchSpy = vi
      .spyOn(integration, 'searchDatasets')
      .mockResolvedValue({
        datasets: [{ id: 'ds000224', name: 'MSC' }],
        total_count: 1,
        page: 1,
        page_size: 100,
        facets: { sources: [], modalities: [], tasks: [] },
      } as any)

    const result = await integration.loadFromBRKG('OpenNeuro')

    expect(searchSpy).toHaveBeenCalledWith(
      undefined,
      { sources: ['OpenNeuro'] },
      1,
      100,
    )
    expect(result).toEqual([{ id: 'ds000224', name: 'MSC' }])
  })

  it('falls back to unfiltered dataset search when the filtered lookup fails', async () => {
    const { DatasetIntegration } = await import('@/lib/dataset-integration')
    const integration = new DatasetIntegration()
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const searchSpy = vi
      .spyOn(integration, 'searchDatasets')
      .mockRejectedValueOnce(new Error('proxy unavailable'))
      .mockResolvedValueOnce({
        datasets: [{ id: 'ds000005', name: 'fallback' }],
        total_count: 1,
        page: 1,
        page_size: 20,
        facets: { sources: [], modalities: [], tasks: [] },
      } as any)

    const result = await integration.loadFromBRKG('HCP')

    expect(searchSpy).toHaveBeenNthCalledWith(
      1,
      undefined,
      { sources: ['HCP'] },
      1,
      100,
    )
    expect(searchSpy).toHaveBeenNthCalledWith(2)
    expect(warnSpy).toHaveBeenCalled()
    expect(result).toEqual([{ id: 'ds000005', name: 'fallback' }])
  })

  it('uses the orchestrator dataset surface and normalizes legacy result shape', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          datasets: [{ id: 'ds000224', name: 'MSC' }],
          total: 1,
          limit: 10,
          offset: 10,
          facets: { sources: [], modalities: [], tasks: [] },
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      ),
    )

    const { DatasetIntegration } = await import('@/lib/dataset-integration')
    const integration = new DatasetIntegration()

    const result = await integration.searchDatasets(
      'memory',
      { sources: ['OpenNeuro'], modalities: ['fMRI'] },
      2,
      10,
      'subjects',
      'desc',
    )

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/datasets?limit=10&offset=10&sort=subjects&order=desc&query=memory&source_repo=OpenNeuro&modalities=fMRI',
    )
    expect(result).toEqual({
      datasets: [{ id: 'ds000224', name: 'MSC' }],
      total_count: 1,
      page: 2,
      page_size: 10,
      facets: { sources: [], modalities: [], tasks: [] },
    })
  })
})

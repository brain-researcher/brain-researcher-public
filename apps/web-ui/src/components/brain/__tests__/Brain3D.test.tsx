// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Brain3D } from '../Brain3D'

vi.mock('@niivue/niivue', () => ({
  Niivue: class MockNiivue {
    volumes: any[] = []
    gl = {
      canvas: { width: 0, height: 0 },
      viewport: vi.fn(),
    }
    canvas: HTMLCanvasElement | null = null
    scene = { pan2Dxyzmm: [0, 0, 0, 1] }
    sliceTypeAxial = 0
    sliceTypeCoronal = 1
    sliceTypeSagittal = 2
    sliceTypeRender = 3
    sliceTypeMultiplanar = 4

    attachToCanvas(canvas: HTMLCanvasElement) {
      this.canvas = canvas
    }

    async loadFromArrayBuffer(_buffer: ArrayBuffer, name: string) {
      this.volumes.push({ name, toRAS: undefined, opacity: 1, cal_min: 0, cal_max: 1 })
    }

    setSliceType = vi.fn()
    updateGLVolume = vi.fn()
    drawScene = vi.fn()
    resizeListener = vi.fn()
    dispose = vi.fn()
    setOpacity = vi.fn()
    setCalMinMax = vi.fn()
  },
}))

describe('Brain3D', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('shows a visible load error and retries when volume loading fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      })

    global.fetch = fetchMock as typeof global.fetch

    render(
      <Brain3D
        config={{
          baseVolume: '/missing/base.nii.gz',
          overlays: [{ name: 'zstat.nii.gz', url: '/missing/zstat.nii.gz' }],
        }}
      />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('brain3d-error')).toBeInTheDocument()
    })

    expect(screen.getByText('Unable to render this brain map')).toBeInTheDocument()
    expect(screen.getByText(/Failed to load any brain volumes/i)).toBeInTheDocument()

    const callsBeforeRetry = fetchMock.mock.calls.length
    fireEvent.click(screen.getByTestId('brain3d-retry'))

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeRetry)
    })
  })
})

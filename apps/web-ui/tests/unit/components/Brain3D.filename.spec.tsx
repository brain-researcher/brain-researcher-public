import { cleanup, render, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import React from 'react'

const mockLoadFromArrayBuffer = vi.fn(async (_buf: ArrayBuffer, name?: string) => {
  (globalThis as any).__lastNvName = name ?? null
})

vi.mock('@niivue/niivue', () => {
  class MockNiivue {
    canvas: HTMLCanvasElement | null = null
    volumes: any[] = []
    sliceTypeAxial = 'axial'
    sliceTypeCoronal = 'coronal'
    sliceTypeSagittal = 'sagittal'
    sliceTypeRender = 'render'
    sliceTypeMultiplanar = 'mosaic'
    gl = {
      canvas: { width: 0, height: 0 },
      viewport: () => {},
    }
    resizeListener = () => {}

    attachToCanvas(canvas: HTMLCanvasElement) {
      this.canvas = canvas
    }

    setSliceType() {}

    removeVolume(volume: any) {
      this.volumes = this.volumes.filter((v) => v !== volume)
    }

    async loadFromArrayBuffer(buffer: ArrayBuffer, name?: string) {
      await mockLoadFromArrayBuffer(buffer, name)
      this.volumes.push({ name })
      return {}
    }

    updateGLVolume() {}
    drawScene() {}
  }

  return { Niivue: MockNiivue }
})

import { Brain3D } from '@/components/brain/Brain3D'

const makeResponse = (headers: Record<string, string>) =>
  new Response(new Uint8Array([1, 2, 3]).buffer, { headers })

describe('<Brain3D> filename plumbing', () => {
  beforeEach(() => {
    (globalThis as any).__lastNvName = null
    mockLoadFromArrayBuffer.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    cleanup()
  })

  it('passes query-param filename through to Niivue load', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(makeResponse({ 'content-type': 'application/gzip' }) as Response)

    render(
      <Brain3D
        config={{ baseVolume: '/api/viz/demo/base?filename=spec_base.nii.gz', overlays: [] }}
        height="200px"
      />,
    )

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await waitFor(() => expect((globalThis as any).__lastNvName).toBe('spec_base.nii.gz'))
  })

  it('falls back to Content-Disposition filename when query missing', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeResponse({
        'content-type': 'application/gzip',
        'content-disposition': 'attachment; filename="aligned_sample.nii.gz"',
      }) as Response,
    )

    render(<Brain3D config={{ baseVolume: '/api/viz/demo/base', overlays: [] }} height="200px" />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await waitFor(() => expect((globalThis as any).__lastNvName).toBe('aligned_sample.nii.gz'))
  })
})

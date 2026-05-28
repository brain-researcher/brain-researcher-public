import { describe, expect, it } from 'vitest'
import { resolveVolumeName } from '@/lib/niivue/resolveVolumeName'

const mockResponse = (headers: Record<string, string>) =>
  new Response(new Uint8Array([0]).buffer, { headers })

describe('resolveVolumeName', () => {
  it('prefers ?filename when provided (keeps extension)', () => {
    const name = resolveVolumeName('/api/viz/demo/base?filename=my_map.nii.gz')
    expect(name).toBe('my_map.nii.gz')
  })

  it('appends .nii.gz when query filename lacks extension', () => {
    const name = resolveVolumeName('/api/viz/demo/base?filename=brain_map')
    expect(name).toBe('brain_map.nii.gz')
  })

  it('handles RFC5987 filename* in Content-Disposition', () => {
    const res = mockResponse({ 'content-disposition': "attachment; filename*=UTF-8''%E6%B4%BB%E6%80%A7.nii.gz" })
    const name = resolveVolumeName('/api/viz/demo/overlay', res)
    expect(name).toBe('活性.nii.gz')
  })

  it('falls back to filename="..." header when param missing', () => {
    const res = mockResponse({ 'content-disposition': 'attachment; filename="aligned.nii.gz"' })
    const name = resolveVolumeName('/api/viz/demo/base', res)
    expect(name).toBe('aligned.nii.gz')
  })

  it('uses URL path when query/header absent', () => {
    const name = resolveVolumeName('/api/viz/demo/base_files/sample.nii')
    expect(name).toBe('sample.nii')
  })

  it('falls back to provided default when nothing else available', () => {
    const name = resolveVolumeName('', undefined, 'fallback.nii.gz')
    expect(name).toBe('fallback.nii.gz')
  })
})

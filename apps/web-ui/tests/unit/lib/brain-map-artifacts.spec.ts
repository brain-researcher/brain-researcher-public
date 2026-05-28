import { describe, expect, it } from 'vitest'
import {
  extractArtifactName,
  extractArtifactUrl,
  isBrainMapArtifact,
  pickPreferredBrainMapArtifact,
} from '@/lib/brain-map-artifacts'

describe('brain-map-artifacts', () => {
  it('extracts artifact name and url from loose artifact shapes', () => {
    const artifact = {
      name: 'z_map.nii.gz',
      url: '/artifacts/z_map.nii.gz',
    }

    expect(extractArtifactName(artifact)).toBe('z_map.nii.gz')
    expect(extractArtifactUrl(artifact)).toBe('/artifacts/z_map.nii.gz')
  })

  it('recognizes NIfTI files by extension, including query strings and hashes', () => {
    expect(isBrainMapArtifact({ url: '/artifacts/stat_map.nii.gz?token=abc#viewer' })).toBe(true)
    expect(isBrainMapArtifact({ url: '/artifacts/raw_mask.nii' })).toBe(true)
  })

  it('prefers download_url over url when both are present', () => {
    expect(
      extractArtifactUrl({
        url: '/artifacts/preview/stat_map.png',
        download_url: '/api/jobs/job_1/artifacts/files/outputs/stat_map.nii.gz',
      }),
    ).toBe('/api/jobs/job_1/artifacts/files/outputs/stat_map.nii.gz')
  })

  it('recognizes NIfTI files when the name carries the extension', () => {
    expect(
      isBrainMapArtifact({
        url: '/artifacts/download/123',
        name: 'contrast_map.nii.gz',
      }),
    ).toBe(true)
  })

  it('recognizes NIfTI files when metadata format is nifti', () => {
    expect(
      isBrainMapArtifact({
        url: '/artifacts/download/123',
        metadata: { format: 'NIFTI' },
      }),
    ).toBe(true)

    expect(
      isBrainMapArtifact({
        url: '/artifacts/download/456',
        meta: { format: 'nifti' },
      }),
    ).toBe(true)
  })

  it('returns false for null artifacts or artifacts without a usable url', () => {
    expect(isBrainMapArtifact(null)).toBe(false)
    expect(isBrainMapArtifact(undefined)).toBe(false)
    expect(isBrainMapArtifact({ name: 'stat_map.nii.gz' })).toBe(false)
    expect(isBrainMapArtifact({ url: '   ' })).toBe(false)
  })

  it('prefers likely statistical maps over generic NIfTI artifacts', () => {
    const first = { name: 'raw_mask.nii.gz', url: '/artifacts/raw_mask.nii.gz' }
    const second = {
      name: 'subject_contrast_map.nii.gz',
      url: '/artifacts/subject_contrast_map.nii.gz',
    }
    const third = { name: 'anatomical.nii.gz', url: '/artifacts/anatomical.nii.gz' }

    expect(pickPreferredBrainMapArtifact([first, second, third])).toBe(second)
  })

  it('falls back to the first NIfTI artifact when no preferred keyword matches', () => {
    const first = { name: 'brain_mask.nii.gz', url: '/artifacts/brain_mask.nii.gz' }
    const second = { name: 'anatomical.nii.gz', url: '/artifacts/anatomical.nii.gz' }

    expect(pickPreferredBrainMapArtifact([first, second])).toBe(first)
  })

  it('returns null when there is no brain-map candidate', () => {
    expect(
      pickPreferredBrainMapArtifact([
        { name: 'report.html', url: '/artifacts/report.html' },
        { name: 'table.csv', url: '/artifacts/table.csv' },
      ]),
    ).toBeNull()
  })
})

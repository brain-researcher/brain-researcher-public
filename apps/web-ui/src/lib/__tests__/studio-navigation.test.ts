import { describe, expect, it } from 'vitest'

import {
  buildDatasetsPickerHref,
  buildStudioDatasetsPickerHref,
  buildStudioPlanHref,
  isTruthyQueryValue,
} from '@/lib/studio-navigation'

describe('studio-navigation', () => {
  it('normalizes studio returnTo links for plan review', () => {
    const params = new URLSearchParams('pipeline=nilearn_connectivity&pickDataset=1&onboarding=true')
    expect(buildStudioPlanHref(params)).toBe('/studio?pipeline=nilearn_connectivity&tab=plan')
  })

  it('builds canonical dataset picker links from studio params', () => {
    const params = new URLSearchParams('pipeline=nilearn_connectivity&pick_dataset=1')
    expect(buildStudioDatasetsPickerHref(params)).toBe(
      '/datasets?pick=1&returnTo=%2Fstudio%3Fpipeline%3Dnilearn_connectivity%26tab%3Dplan',
    )
  })

  it('detects truthy legacy picker flags', () => {
    expect(isTruthyQueryValue('1')).toBe(true)
    expect(isTruthyQueryValue('true')).toBe(true)
    expect(isTruthyQueryValue('yes')).toBe(true)
    expect(isTruthyQueryValue('0')).toBe(false)
    expect(isTruthyQueryValue(null)).toBe(false)
  })

  it('wraps explicit studio returnTo values for canonical picker links', () => {
    expect(buildDatasetsPickerHref('/studio?tab=plan')).toBe(
      '/datasets?pick=1&returnTo=%2Fstudio%3Ftab%3Dplan',
    )
  })
})

import { describe, expect, it } from 'vitest'

import {
  buildReadableLabel,
  canonicalizeUrl,
  inferEvidenceQuality,
  inferSourceType,
  normalizeEvidenceUrl,
  resolveGroundingRedirect,
} from '@/lib/server/evidence-normalizer'

describe('evidence normalizer', () => {
  it('canonicalizes URL and strips tracking params', () => {
    const value = canonicalizeUrl(
      'https://WWW.Example.org:443/papers/decoding?utm_source=x&b=2&a=1#section',
    )
    expect(value).toBe('https://example.org/papers/decoding?a=1&b=2')
  })

  it('unwraps grounding redirect URLs from query parameters', async () => {
    const wrapped =
      'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ?url=https%3A%2F%2Fexample.org%2Fpaper%3Futm_source%3Dgoogle'
    const resolved = await resolveGroundingRedirect({ url: wrapped })
    expect(resolved).toBe('https://example.org/paper')
  })

  it('builds readable labels when source title is generated', () => {
    const label = buildReadableLabel({
      title: 'nested-1',
      fallbackId: 'doc_2',
      url: 'https://openneuro.org/datasets/ds000030',
      index: 0,
    })
    expect(label.toLowerCase()).toContain('ds000030')
    expect(label.toLowerCase()).toContain('openneuro.org')
  })

  it('normalizes evidence URL metadata used by UI', async () => {
    const normalized = await normalizeEvidenceUrl({
      url: 'https://www.ncbi.nlm.nih.gov/pubmed/12345?utm_source=test',
      resolveRedirects: false,
    })
    expect(normalized.url).toBe('https://ncbi.nlm.nih.gov/pubmed/12345')
    expect(normalized.finalUrl).toBe('https://ncbi.nlm.nih.gov/pubmed/12345')
    expect(normalized.sourceHost).toBe('ncbi.nlm.nih.gov')
    expect(normalized.displayUrl).toContain('ncbi.nlm.nih.gov/pubmed/12345')
  })

  it('unwraps redirect target without network resolution budget', async () => {
    const normalized = await normalizeEvidenceUrl({
      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ?url=https%3A%2F%2Fexample.org%2Fpaper%3Futm_source%3Dx',
      resolveRedirects: true,
      allowNetworkResolve: false,
    })
    expect(normalized.finalUrl).toBe('https://example.org/paper')
    expect(normalized.resolution.resolvedVia).toBe('query_param')
    expect(normalized.resolution.isGroundingRedirect).toBe(false)
  })

  it('marks unresolved redirect metadata when network resolution is skipped by budget', async () => {
    const normalized = await normalizeEvidenceUrl({
      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEXAMPLE',
      resolveRedirects: true,
      allowNetworkResolve: false,
      skippedByBudget: true,
    })
    expect(normalized.url).toContain('vertexaisearch.cloud.google.com/grounding-api-redirect')
    expect(normalized.resolution.isGroundingRedirect).toBe(true)
    expect(normalized.resolution.skippedByBudget).toBe(true)
  })

  it('infers dataset source types from known hosts', () => {
    expect(inferSourceType('https://openneuro.org/datasets/ds000030')).toBe('dataset')
    expect(inferSourceType('https://doi.org/10.1038/s41593-024-00001-1')).toBe('paper')
  })

  it('assigns evidence quality by traceability signals instead of hard domain blacklist', () => {
    const secondary = inferEvidenceQuality({
      url: 'https://www.news-medical.net/news/20250101/fmri-decoding-overview.aspx',
      title: 'fMRI decoding overview',
      kind: 'paper',
    })
    expect(secondary.tier).toBe('secondary')

    const primary = inferEvidenceQuality({
      url: 'https://example.org/paper/10.1038/s41593-024-00001-1',
      title: 'doi:10.1038/s41593-024-00001-1',
      kind: 'paper',
    })
    expect(primary.tier).toBe('primary')
  })
})

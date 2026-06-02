import { test, expect } from '@playwright/test'

const BASE =
  process.env.E2E_BASE_URL ??
  process.env.BASE_URL ??
  'http://localhost:3000'

const ROUTES = [
  '/',
  '/studio',
  '/datasets',
  '/library',
  '/library/tools',
  '/kg',
  '/pipeline',
  '/pipeline-builder',
  '/demos',
  '/settings',
  '/viz',
  '/charts',
]

test.describe('Route smoke', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('studio route renders or redirects to auth gate', async ({ page }) => {
    await page.goto(`${BASE}/studio`, { waitUntil: 'domcontentloaded' })
    const loginHeading = page.getByRole('heading', { name: /Sign in to your account/i })
    const studioHeading = page.getByRole('heading', { name: /^Studio$/i }).first()
    const planTab = page.getByRole('tab', { name: /^Plan$/i }).first()
    const startFromScratchButton = page.getByRole('button', { name: /^Start from scratch$/i }).first()

    const outcome = await Promise.race([
      loginHeading.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'login' as const),
      startFromScratchButton.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'picker' as const),
      planTab.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'plan' as const),
      studioHeading.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'studio' as const),
    ]).catch(() => 'unknown' as const)

    if (outcome === 'login') {
      await expect(page).toHaveURL(/\/auth\/login/, { timeout: 30_000 })
      return
    }

    await expect(page).toHaveURL(/\/studio(?:\?|$)/, { timeout: 30_000 })

    if (outcome === 'picker') {
      await startFromScratchButton.click()
      await expect(planTab).toBeVisible({ timeout: 15_000 })
    } else if (outcome === 'unknown') {
      const skipButton = page.getByRole('button', { name: /Skip, start with empty workspace/i }).first()
      if (await skipButton.isVisible().catch(() => false)) {
        await skipButton.click()
      } else {
        await page.keyboard.press('Escape')
      }
      await expect(planTab).toBeVisible({ timeout: 15_000 })
    } else if (outcome === 'studio') {
      await expect(studioHeading).toBeVisible()
    } else {
      await expect(planTab).toBeVisible()
    }
  })

  test('/en/* redirects to /* (preserves query)', async ({ page }) => {
    await page.goto(`${BASE}/en/explore?from=e2e`, { waitUntil: 'domcontentloaded' })
    await expect
      .poll(() => {
        const url = new URL(page.url())
        return {
          pathname: url.pathname,
          from: url.searchParams.get('from'),
        }
      })
      .toEqual(
        expect.objectContaining({
          from: 'e2e',
        }),
      )
    expect(new URL(page.url()).pathname.startsWith('/en')).toBe(false)
  })

  test('critical routes return 200 (HEAD/GET)', async ({ page }) => {
    test.setTimeout(120_000)
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    for (const path of ROUTES) {
      const url = `${BASE}${path}`
      let res = await page.request
        .head(url, { timeout: 15_000 })
        .catch(() => null)

      // Some routes may not support HEAD; fall back to GET with a larger timeout.
      if (!res || res.status() >= 400) {
        res = await page.request.get(url, { timeout: 60_000 })
      }

      expect(res.status(), `GET ${path}`).toBeLessThan(400)
    }
  })

  test('knowledge graph renders publicly and pipeline renders or auth-gates', async ({ page }) => {
    await page.goto(`${BASE}/kg`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /Knowledge Graph/i }).first()).toBeVisible()

    await page.goto(`${BASE}/pipeline`, { waitUntil: 'domcontentloaded' })
    const loginHeading = page.getByRole('heading', { name: /Sign in to your account/i })
    const pipelineHeading = page.getByRole('heading', { name: /Pipeline Management/i }).first()

    const outcome = await Promise.race([
      loginHeading.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'login' as const),
      pipelineHeading.waitFor({ state: 'visible', timeout: 7000 }).then(() => 'pipeline' as const),
    ]).catch(() => 'unknown' as const)

    if (outcome === 'login') {
      await expect(page).toHaveURL(/\/auth\/login\?callbackUrl=%2Fpipeline(?:$|&)/, {
        timeout: 30_000,
      })
      return
    }

    await expect(page).toHaveURL(/\/pipeline(?:\?|$)/, { timeout: 30_000 })
    await expect(pipelineHeading).toBeVisible()
  })

  test('datasets page renders heading', async ({ page }) => {
    await page.goto(`${BASE}/datasets`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /^Datasets$/i }).first()).toBeVisible()
  })

  test('legacy vault datasets redirects to /datasets', async ({ page }) => {
    await page.goto(`${BASE}/vault/datasets?from=e2e`, { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/datasets\?from=e2e$/, { timeout: 15_000 })
    await expect(page.getByRole('heading', { name: /^Datasets$/i }).first()).toBeVisible()
  })
})

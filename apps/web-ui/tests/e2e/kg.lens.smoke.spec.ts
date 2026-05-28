import { test, expect, type Page } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'

test.describe.configure({ mode: 'serial', timeout: 90_000 })

function tabOrButton(page: Page, label: RegExp) {
  return page
    .locator('[role="tab"], button')
    .filter({ hasText: label })
    .first()
}

test('KG task lens shell renders with entity details', async ({ page }) => {
  await page.goto(`${BASE}/kg`, { waitUntil: 'domcontentloaded' })

  // Fail fast with a clear reason if auth routing regresses.
  const signInHeading = page.getByRole('heading', { name: /sign in to your account/i }).first()
  await expect(signInHeading).toHaveCount(0)

  const taskTab = tabOrButton(page, /^Task$/i)
  const diseaseTab = tabOrButton(page, /^Disease$/i)
  const onvocTab = tabOrButton(page, /^ONVOC$/i)
  await expect(taskTab).toBeVisible()
  await expect(diseaseTab).toBeVisible()
  await expect(onvocTab).toBeVisible()

  await expect(page.getByText(/^Task Families$/i).first()).toBeVisible({ timeout: 45_000 })
  await expect(page.getByText(/^Overview$/i).first()).toBeVisible({ timeout: 45_000 })
  await expect(
    page.locator('text=/(tf_[a-z0-9_]+:|neurostore_task:[^\\s]+|neo4j:task)/i').first(),
  ).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('button', { name: /^Ask the KG$/i }).first()).toBeVisible({
    timeout: 45_000,
  })
})

test('KG view controls are clickable without crashing', async ({ page }) => {
  await page.goto(`${BASE}/kg`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(/^Task Families$/i).first()).toBeVisible({ timeout: 45_000 })

  const views = ['Graph', 'Explorer', 'Maps/Coords']
  let clicked = 0

  for (const label of views) {
    const btn = page.getByRole('button', { name: new RegExp(`^${label.replace('/', '\\/')}$`, 'i') }).first()
    const count = await btn.count()
    if (!count) continue
    if (await btn.isDisabled()) continue

    await btn.click({ timeout: 10_000 })
    clicked += 1
    await page.waitForTimeout(250)

    // Keep the assertion coarse to avoid coupling to implementation details.
    await expect(page.getByText(/Something went wrong/i)).toHaveCount(0)
  }

  expect(clicked).toBeGreaterThan(0)
  await expect(page).toHaveURL(/\/kg/, { timeout: 10_000 })
  await expect(page.getByText(/^Overview$/i).first()).toBeVisible({ timeout: 20_000 })
})

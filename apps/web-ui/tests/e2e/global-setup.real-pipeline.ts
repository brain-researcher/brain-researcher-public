import fs from 'node:fs'
import path from 'node:path'

import { chromium, type FullConfig } from '@playwright/test'

const E2E_AUTH_COOKIE = 'br_e2e_auth'
const ACCESS_TOKEN_COOKIE = 'br_access_token'

async function globalSetup(config: FullConfig) {
  const baseURL =
    process.env.BR_WEB_URL ||
    process.env.E2E_BASE_URL ||
    process.env.BASE_URL ||
    (config.projects[0]?.use?.baseURL as string | undefined) ||
    'http://localhost:3002'

  const token =
    process.env.BR_TEST_TOKEN ||
    process.env.E2E_AUTH_TOKEN ||
    process.env.BR_AUTH_TOKEN ||
    ''

  if (!token) {
    throw new Error(
      'Real pipeline E2E requires a bearer token. Set BR_TEST_TOKEN (preferred) or E2E_AUTH_TOKEN.',
    )
  }

  const repoRoot = path.resolve(__dirname, '../../../..')
  const storageStatePath = path.join(
    repoRoot,
    'artifacts',
    'playwright-real',
    '.auth',
    'storageState.json',
  )
  fs.mkdirSync(path.dirname(storageStatePath), { recursive: true })

  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()

  await page.goto(baseURL, { waitUntil: 'domcontentloaded' })

  // Allow navigating protected pages without requiring NextAuth sign-in.
  await context.addCookies([
    {
      name: E2E_AUTH_COOKIE,
      value: '1',
      url: baseURL,
    },
    // Provide bearer token to server middleware so /api/* routes can validate + forward auth.
    {
      name: ACCESS_TOKEN_COOKIE,
      value: token,
      url: baseURL,
    },
  ])

  await context.storageState({ path: storageStatePath })
  await browser.close()
}

export default globalSetup

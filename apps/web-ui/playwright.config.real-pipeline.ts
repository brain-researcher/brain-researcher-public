import path from 'node:path'

import { defineConfig, devices } from '@playwright/test'

const repoRoot = path.resolve(__dirname, '../..')
const playwrightArtifactsDir = path.join(repoRoot, 'artifacts', 'playwright-real')
const playwrightReportDir = path.join(repoRoot, 'artifacts', 'playwright-report-real')
const storageStatePath = path.join(playwrightArtifactsDir, '.auth', 'storageState.json')

/**
 * Real pipeline execution E2E config.
 *
 * This suite is opt-in and expects a running Agent + Orchestrator stack.
 * It does NOT run in the normal PRD gate.
 */
const externalBaseUrl =
  process.env.BR_WEB_URL ?? process.env.E2E_BASE_URL ?? process.env.BASE_URL
const localBaseUrl = 'http://localhost:3002'
const baseURL = externalBaseUrl ?? localBaseUrl

const stripTrailingSlash = (value: string) => value.replace(/\/+$/, '')

const deriveWsBaseUrl = (value: string) => {
  try {
    const url = new URL(stripTrailingSlash(value))
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = '/ws'
    url.search = ''
    url.hash = ''
    return stripTrailingSlash(url.toString())
  } catch {
    return 'ws://localhost:3001/ws'
  }
}

const agentBaseUrl =
  process.env.BR_AGENT_URL ??
  process.env.AGENT_BASE_URL ??
  process.env.BR_AGENT_BASE_URL ??
  process.env.AGENT_URL ??
  'http://localhost:8000'
const orchestratorBaseUrl =
  process.env.BR_ORCHESTRATOR_URL ??
  process.env.ORCHESTRATOR_BASE_URL ??
  process.env.BR_ORCHESTRATOR_BASE_URL ??
  process.env.ORCHESTRATOR_URL ??
  'http://localhost:3001'
const kgBaseUrl =
  process.env.BR_KG_URL ??
  process.env.BR_NEUROKG_URL ??
  process.env.KG_API_URL ??
  process.env.NEUROKG_API_URL ??
  process.env.KG_URL ??
  process.env.NEUROKG_URL ??
  'http://localhost:5000'
const wsBaseUrl =
  process.env.NEXT_PUBLIC_WS_URL ??
  process.env.WS_URL ??
  deriveWsBaseUrl(orchestratorBaseUrl)

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['**/real.pipeline-execution.spec.ts'],
  globalSetup: './tests/e2e/global-setup.real-pipeline.ts',

  // Real runs can take minutes; set generous defaults (override per-test as needed).
  timeout: 15 * 60_000,
  expect: {
    timeout: 30_000,
  },

  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,

  reporter: [
    ['line'],
    ['html', { outputFolder: playwrightReportDir, open: 'never' }],
    ['json', { outputFile: path.join(playwrightArtifactsDir, 'results.json') }],
  ],

  use: {
    baseURL,
    storageState: storageStatePath,

    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',

    viewport: { width: 1280, height: 720 },
    ignoreHTTPSErrors: true,
    actionTimeout: 60_000,
    navigationTimeout: 60_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  outputDir: playwrightArtifactsDir,

  webServer: externalBaseUrl
    ? undefined
    : {
        command: [
          // Avoid ENOSPC when inotify watcher limits are low (common in CI/containers).
          'WATCHPACK_POLLING=true',
          'NEXT_PUBLIC_USE_API_PROXY=true',
          `BR_AGENT_URL=${agentBaseUrl}`,
          `BR_ORCHESTRATOR_URL=${orchestratorBaseUrl}`,
          `BR_KG_URL=${kgBaseUrl}`,
          `NEXT_PUBLIC_WS_URL=${wsBaseUrl}`,
          'npm run dev:3002',
        ].join(' '),
        url: localBaseUrl,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
})

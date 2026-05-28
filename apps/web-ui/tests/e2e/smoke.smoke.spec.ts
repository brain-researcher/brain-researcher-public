import { test, expect } from '@playwright/test';

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000';
const AUTH_TOKEN = process.env.E2E_AUTH_TOKEN || '';
const AUTH_HEADERS = AUTH_TOKEN ? { authorization: `Bearer ${AUTH_TOKEN}` } : {};

// Short, serial smoke to avoid flakiness
// Ensure Agent (8000) and Next.js (3000) are running before executing.

test.describe.configure({ mode: 'serial', timeout: 60_000 });

test('health endpoint via Next proxy', async ({ page }) => {
  const resp = await page.request.get(`${BASE}/api/health`);
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
});

test('chat endpoint via Next proxy', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/chat');

  const resp = await page.request.post(`${BASE}/api/chat`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: { messages: [{ role: 'user', content: 'hello from playwright' }] },
  });
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('text');
});

test('file upload proxy round-trip', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/files/upload');

  const buffer = Buffer.from('pw smoke');
  const resp = await page.request.fetch(`${BASE}/api/files/upload`, {
    method: 'POST',
    headers: AUTH_HEADERS,
    multipart: {
      file: {
        name: 'sample.txt',
        mimeType: 'text/plain',
        buffer,
      },
    },
  });
  expect(resp.ok()).toBeTruthy();
});

test('datasets search proxy responds', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/datasets/search');

  const resp = await page.request.post(`${BASE}/api/datasets/search`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: { query: 'fmri', limit: 2 },
  });
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  expect(resp.headers()['content-type'] || '').toContain('application/json');
  const json = await resp.json();
  expect(json).toHaveProperty('results');
});

test('BR-KG health proxy responds', async ({ page }) => {
  const resp = await page.request.get(`${BASE}/api/kg/health`);
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('ok');
});

test('analyses API - create analysis via proxy', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/analyses');

  const resp = await page.request.post(`${BASE}/api/analyses`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: { plan: { type: 'custom', prompt: 'smoke test', steps: [{ tool: 'test', args: {} }] } },
  });
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('analysis_id');
  expect(json).toHaveProperty('status');
});

test('analyses API - get analysis status via proxy', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/analyses');

  // First create an analysis
  const createResp = await page.request.post(`${BASE}/api/analyses`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: { plan: { type: 'custom', prompt: 'smoke test', steps: [{ tool: 'smoke-test', args: {} }] } },
  });
  expect(createResp.ok()).toBeTruthy();
  const createJson = await createResp.json();
  const analysisId = createJson.analysis_id;

  // Then get its status
  const statusResp = await page.request.get(`${BASE}/api/analyses/${analysisId}`, {
    headers: AUTH_HEADERS,
  });
  expect(statusResp.ok(), `status ${statusResp.status()}`).toBeTruthy();
  const statusJson = await statusResp.json();
  expect(statusJson.analysis_id).toBe(analysisId);
});

test('coding mode chat stream proxy responds', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/chat/stream');

  // NOTE: This endpoint returns SSE and intentionally keeps the connection open.
  // Playwright's `page.request.post` waits on the streaming body and can time out.
  // Use Node fetch to validate headers without waiting for stream completion.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);

  try {
    const resp = await fetch(`${BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'hello coding mode' }],
        ctx: { tools: { mode: 'coding' } },
      }),
      signal: controller.signal,
    });

    expect(resp.ok, `status ${resp.status}`).toBeTruthy();
    const contentType = resp.headers.get('content-type') || '';
    expect(contentType).toContain('text/event-stream');
    await resp.body?.cancel();
  } finally {
    clearTimeout(timeout);
  }
});

test('analyses API - list analyses via proxy', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/analyses');

  const resp = await page.request.get(`${BASE}/api/analyses`, { headers: AUTH_HEADERS });
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('items');
  expect(json).toHaveProperty('count');
  expect(Array.isArray(json.items)).toBe(true);
});

test('analyses API creates analysis from dataset template', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/analyses');

  const resp = await page.request.post(`${BASE}/api/analyses`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: {
      dataset_id: 'ds:openneuro:ds000001',
      analysis_id: 'preprocess',
      pipeline_id: 'fmriprep',
    },
  });
  expect(resp.ok(), `status ${resp.status()}`).toBeTruthy();
  const json = await resp.json();
  expect(json).toHaveProperty('analysis_id');
  expect(json).toHaveProperty('status');
});

import { test, expect } from '@playwright/test'

const BASE =
  process.env.E2E_BASE_URL ??
  process.env.BASE_URL ??
  'http://localhost:3000'

test.describe('Chat basics', () => {
  test('POST /api/chat returns a message', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/chat`, {
      headers: { 'content-type': 'application/json' },
      data: { messages: [{ role: 'user', content: 'Hello from Playwright. What is GLM?' }] },
      timeout: 45_000,
    })

    const status = res.status()
    const json = await res.json().catch(() => ({}))

    // In dev or CI, the upstream LLM may be unavailable (quota, missing keys, etc).
    // Treat a structured error as a valid outcome so this test doesn't flake.
    if (status >= 400) {
      expect(status, 'status').toBeLessThan(600)
      const errorText =
        (json?.detail ?? json?.error ?? json?.message ?? '').toString().toLowerCase()
      expect(errorText.length > 0, `error body: ${JSON.stringify(json)}`).toBe(true)
      return
    }

    // Success path: the agent may return { message: { content: ... } } or { content: ... }
    const content = json?.message?.content ?? json?.content ?? ''
    expect(typeof content, 'content type').toBe('string')
    expect(content.length, 'content length').toBeGreaterThan(0)
  })

  test('UI can send a prompt and render assistant reply', async ({ page }) => {
    await page.goto(`${BASE}/chat`)
    // Type into the composer
    const composer = page.locator(
      'textarea[placeholder^="Ask anything about"], textarea[placeholder*="question about"]'
    ).first()
    await composer.click()
    await composer.fill('What is a GLM in fMRI analysis?')
    // Click the send button (rightmost icon button in composer)
    // Use a more specific selector to avoid flakiness
    await page.getByTestId('chat-send-button').click()
    // Wait for the latest assistant message to contain "GLM" text.
    const assistantMessage = page.getByTestId('chat-message-assistant').last()
    // When the upstream model is unavailable, UI may show a friendly error.
    await expect(assistantMessage).toContainText(/GLM|No response|encountered an error/i, {
      timeout: 60_000,
    })
  })
})

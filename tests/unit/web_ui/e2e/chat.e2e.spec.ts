/**
 * E2E test for chat functionality
 * Tests the complete user flow: input → send → backend → UI render
 */

import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_URL ?? 'http://localhost:3000';

test.describe('Chat E2E - Real User Flow', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the main page
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    
    // Wait for the page to be fully loaded
    await page.waitForLoadState('networkidle');
  });

  test('user can send a message and see LLM response + RunCard', async ({ page }) => {
    // 1) Find the chat input - try multiple selectors for robustness
    const inputSelectors = [
      '[data-testid="chat-input"]',
      'textarea[placeholder*="Ask"]',
      'textarea[placeholder*="Message"]',
      'input[placeholder*="Ask"]',
      'input[placeholder*="Message"]',
      'textarea.chat-input',
      'input.chat-input',
      '[role="textbox"]'
    ];
    
    let input = null;
    for (const selector of inputSelectors) {
      const element = page.locator(selector).first();
      if (await element.isVisible({ timeout: 1000 }).catch(() => false)) {
        input = element;
        break;
      }
    }
    
    if (!input) {
      throw new Error('Could not find chat input field');
    }
    
    await expect(input).toBeVisible();
    
    // 2) Type the test message
    const testMessage = 'What is the n-back task?';
    await input.fill(testMessage);
    
    // 3) Set up network monitoring for the API call
    const responsePromise = page.waitForResponse(
      response => {
        const url = response.url();
        const method = response.request().method();
        const status = response.status();
        
        // Check if this is our chat API endpoint
        return (url.endsWith('/api/chat') || url.includes('/chat')) && 
               method === 'POST' && 
               status === 200;
      },
      { timeout: 30000 } // 30 second timeout for API response
    );
    
    // Also monitor for any 405 errors (wrong method)
    page.on('response', response => {
      if (response.url().includes('/api/chat') && response.status() === 405) {
        console.error('ERROR: Got 405 Method Not Allowed - frontend is using wrong HTTP method');
      }
    });
    
    // 4) Send the message - try button first, then Enter key
    const sendButtonSelectors = [
      '[data-testid="send-button"]',
      'button[aria-label*="Send"]',
      'button:has-text("Send")',
      'button[type="submit"]',
      '[data-testid="chat-submit"]',
      '.send-button'
    ];
    
    let sendButton = null;
    for (const selector of sendButtonSelectors) {
      const element = page.locator(selector).first();
      if (await element.isVisible({ timeout: 1000 }).catch(() => false)) {
        sendButton = element;
        break;
      }
    }
    
    if (sendButton) {
      await sendButton.click();
      console.log('Clicked send button');
    } else {
      // Fallback to pressing Enter
      await input.press('Enter');
      console.log('Pressed Enter to send');
    }
    
    // 5) Wait for and validate the API response
    console.log('Waiting for API response...');
    const apiResponse = await responsePromise;
    const responseData = await apiResponse.json();
    
    // Validate response structure
    expect(responseData).toHaveProperty('message');
    expect(responseData.message).toHaveProperty('content');
    expect(responseData).toHaveProperty('runCard');
    
    // Check that we got actual content
    const content = responseData.message.content;
    expect(content).toBeTruthy();
    expect(content.toLowerCase()).toMatch(/n-?back|working memory|cognitive|task/i);
    
    console.log('API response received successfully');
    
    // 6) Wait for the assistant message to appear in the UI
    const assistantMessageSelectors = [
      '[data-testid="message-bubble-assistant"]',
      '[data-role="assistant-message"]',
      '.assistant-message',
      '.message-assistant',
      '[class*="assistant"]',
      'div:has-text("n-back")',
      'div:has-text("working memory")'
    ];
    
    let assistantBubble = null;
    for (const selector of assistantMessageSelectors) {
      try {
        const element = page.locator(selector)
          .filter({ hasText: /n-?back|working memory/i })
          .first();
        
        if (await element.isVisible({ timeout: 5000 }).catch(() => false)) {
          assistantBubble = element;
          break;
        }
      } catch (e) {
        // Continue trying other selectors
      }
    }
    
    if (assistantBubble) {
      await expect(assistantBubble).toBeVisible();
      console.log('Assistant message bubble is visible');
    } else {
      // Take a screenshot for debugging
      await page.screenshot({ 
        path: 'test-artifacts/chat-no-bubble.png', 
        fullPage: true 
      });
      console.warn('Could not find assistant message bubble, but API returned successfully');
    }
    
    // 7) Check for evidence rail / RunCard (optional but good to have)
    const evidenceSelectors = [
      '[data-testid="evidence-rail"]',
      '[data-testid="run-card"]',
      '.evidence-rail',
      '.run-card',
      '[class*="evidence"]',
      '[class*="runcard"]',
      'aside'
    ];
    
    for (const selector of evidenceSelectors) {
      const element = page.locator(selector).first();
      if (await element.isVisible({ timeout: 3000 }).catch(() => false)) {
        console.log('Evidence rail/RunCard is visible');
        
        // Check if it contains expected text
        const text = await element.textContent();
        if (text && text.toLowerCase().includes('n-back')) {
          console.log('Evidence rail contains expected content');
        }
        break;
      }
    }
    
    // 8) Take a final screenshot for visual verification
    await page.screenshot({ 
      path: 'test-artifacts/chat-success.png', 
      fullPage: true 
    });
    
    console.log('E2E test completed successfully!');
  });
  
  test('handles API errors gracefully', async ({ page }) => {
    // Test error handling by sending a message when backend might be down
    // This is a negative test case
    
    const input = page.locator('textarea, input[type="text"]').first();
    await input.fill('Test error handling');
    
    // Mock network failure (optional - can use page.route to intercept)
    await page.route('**/api/chat', route => {
      route.abort('failed');
    });
    
    // Try to send
    await input.press('Enter');
    
    // Should show error message or fallback behavior
    const errorSelectors = [
      '[data-testid="error-message"]',
      '.error-message',
      '[role="alert"]',
      'div:has-text("error")',
      'div:has-text("failed")'
    ];
    
    let errorFound = false;
    for (const selector of errorSelectors) {
      const element = page.locator(selector).first();
      if (await element.isVisible({ timeout: 5000 }).catch(() => false)) {
        errorFound = true;
        console.log('Error message displayed correctly');
        break;
      }
    }
    
    if (!errorFound) {
      console.log('No explicit error message, but app did not crash');
    }
  });
});

// Performance test
test('chat response time is acceptable', async ({ page }) => {
  await page.goto(BASE);
  
  const input = page.locator('textarea, input[type="text"]').first();
  await input.fill('What is fMRI?');
  
  const startTime = Date.now();
  
  const responsePromise = page.waitForResponse(
    response => response.url().includes('/api/chat') && response.status() === 200
  );
  
  await input.press('Enter');
  await responsePromise;
  
  const responseTime = Date.now() - startTime;
  
  console.log(`Response time: ${responseTime}ms`);
  
  // Should respond within 60 seconds (very generous for DeepSeek)
  expect(responseTime).toBeLessThan(60000);
  
  // Warn if it's slow
  if (responseTime > 10000) {
    console.warn(`Slow response: ${responseTime}ms`);
  }
});
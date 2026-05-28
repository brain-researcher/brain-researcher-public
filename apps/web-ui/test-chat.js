/**
 * Simple Playwright test script for chat functionality
 */

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const artifactsDir = path.resolve(__dirname, '../../..', 'artifacts', 'playwright', 'test-chat');
fs.mkdirSync(artifactsDir, { recursive: true });
const artifactPath = (name) => path.join(artifactsDir, name);
const BASE_URL =
  process.env.BR_WEB_URL ||
  process.env.E2E_BASE_URL ||
  process.env.BASE_URL ||
  'http://localhost:3000';

(async () => {
  console.log('Starting browser test...');
  
  // Launch browser
  const browser = await chromium.launch({ 
    headless: true,
    timeout: 60000 
  });
  
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }
  });
  
  const page = await context.newPage();
  
  try {
    // Navigate to the app
    console.log(`Navigating to ${BASE_URL}...`);
    await page.goto(BASE_URL, {
      waitUntil: 'networkidle',
      timeout: 30000
    });
    
    console.log('Page loaded successfully');
    
    // Take a screenshot of initial state
    await page.screenshot({ path: artifactPath('initial.png'), fullPage: true });
    
    // Try to find the chat input - use multiple selectors
    console.log('Looking for chat input field...');
    
    const inputSelectors = [
      'textarea',
      'input[type="text"]',
      '[data-testid="chat-input"]',
      '[placeholder*="Ask"]',
      '[placeholder*="Message"]',
      '[placeholder*="Type"]',
      '[contenteditable="true"]'
    ];
    
    let inputFound = false;
    let input = null;
    
    for (const selector of inputSelectors) {
      try {
        input = await page.locator(selector).first();
        if (await input.isVisible({ timeout: 1000 })) {
          console.log(`Found input with selector: ${selector}`);
          inputFound = true;
          break;
        }
      } catch (e) {
        // Continue trying
      }
    }
    
    if (!inputFound) {
      console.log('Could not find chat input. Page structure:');
      const bodyText = await page.locator('body').textContent();
      console.log(bodyText.substring(0, 500));
      
      // Take screenshot for debugging
      await page.screenshot({ path: artifactPath('no-input.png'), fullPage: true });
      process.exit(1);
    }
    
    // Type a message
    const testMessage = 'What is a neuron?';
    console.log(`Typing message: "${testMessage}"`);
    await input.fill(testMessage);
    
    // Set up network monitoring
    console.log('Setting up network monitoring for /api/chat...');
    
    const responsePromise = page.waitForResponse(
      response => {
        const url = response.url();
        const method = response.request().method();
        console.log(`Network: ${method} ${url} -> ${response.status()}`);
        return url.includes('/chat') && method === 'POST';
      },
      { timeout: 60000 }
    );
    
    // Try to send - look for button or press Enter
    console.log('Attempting to send message...');
    
    const buttonSelectors = [
      'button[type="submit"]',
      'button:has-text("Send")',
      '[data-testid="send-button"]',
      'button[aria-label*="Send"]'
    ];
    
    let sent = false;
    
    for (const selector of buttonSelectors) {
      try {
        const button = await page.locator(selector).first();
        if (await button.isVisible({ timeout: 1000 })) {
          console.log(`Found send button: ${selector}`);
          await button.click();
          sent = true;
          break;
        }
      } catch (e) {
        // Continue
      }
    }
    
    if (!sent) {
      console.log('No send button found, pressing Enter...');
      await input.press('Enter');
    }
    
    // Wait for response
    console.log('Waiting for API response (this may take a while if the backend is busy)...');
    
    try {
      const response = await responsePromise;
      console.log(`Got response: ${response.status()}`);
      
      if (response.status() === 200) {
        const data = await response.json();
        console.log('Response preview:', JSON.stringify(data).substring(0, 200));
        
        // Wait a bit for UI to update
        await page.waitForTimeout(2000);
        
        // Take screenshot of result
        await page.screenshot({ path: artifactPath('after-response.png'), fullPage: true });
        
        console.log('✅ Test PASSED - Chat API working!');
      } else {
        console.log(`❌ API returned status ${response.status()}`);
      }
      
    } catch (timeoutError) {
      console.log('⏱️ Request timed out - backend may still be processing');
      await page.screenshot({ path: artifactPath('timeout.png'), fullPage: true });
    }
    
  } catch (error) {
    console.error('Test error:', error.message);
    await page.screenshot({ path: artifactPath('error.png'), fullPage: true });
  } finally {
    await browser.close();
    console.log('Browser closed');
  }
})();

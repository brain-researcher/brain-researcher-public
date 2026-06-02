/**
 * End-to-end tests for real-time collaboration scenarios.
 *
 * Tests complete user workflows, multi-user interactions,
 * brain annotation collaboration, and error recovery scenarios.
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';
import { chromium, firefox, webkit } from '@playwright/test';

// Test configuration
const TEST_CONFIG = {
  baseURL: process.env.TEST_BASE_URL || 'http://localhost:3000',
  wsURL: process.env.TEST_WS_URL || 'ws://localhost:8000',
  timeout: 30000,
  defaultUser: {
    email: 'test@example.com',
    password: 'testpass123',
    name: 'Test User'
  }
};

// Helper functions
class CollaborationHelper {
  constructor(private page: Page) {}

  async navigateToDocument(documentId: string) {
    await this.page.goto(`${TEST_CONFIG.baseURL}/document/${documentId}`);
    await this.page.waitForLoadState('networkidle');
  }

  async waitForCollaborationFeatures() {
    await this.page.waitForSelector('[data-testid="collaboration-features"]', { timeout: 10000 });
  }

  async openCommentsPanel() {
    await this.page.click('[data-testid="comments-button"]');
    await this.page.waitForSelector('[data-testid="comments-panel"]');
  }

  async addComment(text: string) {
    await this.page.fill('[data-testid="comment-input"]', text);
    await this.page.click('[data-testid="send-comment"]');
  }

  async openShareDialog() {
    await this.page.click('[data-testid="share-button"]');
    await this.page.waitForSelector('[data-testid="share-dialog"]');
  }

  async setShareVisibility(visibility: 'private' | 'team' | 'public') {
    await this.page.check(`[data-testid="visibility-${visibility}"]`);
  }

  async copyShareLink() {
    await this.page.click('[data-testid="copy-link"]');
  }

  async getUserCount(): Promise<number> {
    const userCountText = await this.page.textContent('[data-testid="user-count"]');
    const match = userCountText?.match(/(\d+)/);
    return match ? parseInt(match[1], 10) : 0;
  }

  async waitForUserJoin(timeout: number = 5000) {
    await this.page.waitForFunction(
      () => {
        const userCount = document.querySelector('[data-testid="user-count"]')?.textContent;
        return userCount && parseInt(userCount.match(/(\d+)/)?.[1] || '0', 10) > 1;
      },
      { timeout }
    );
  }

  async waitForComment(commentText: string) {
    await this.page.waitForSelector(`text=${commentText}`);
  }

  async getCursorPosition(userId: string): Promise<{ x: number; y: number } | null> {
    return await this.page.evaluate((id) => {
      const cursor = document.querySelector(`[data-testid="cursor-${id}"]`) as HTMLElement;
      if (!cursor) return null;

      const style = cursor.style;
      return {
        x: parseInt(style.left || '0'),
        y: parseInt(style.top || '0')
      };
    }, userId);
  }

  async simulateCursorMovement(x: number, y: number) {
    await this.page.mouse.move(x, y);
  }

  async waitForTypingIndicator(username: string) {
    await this.page.waitForSelector('[data-testid="typing-indicators"]');
    await expect(this.page.locator('[data-testid="typing-indicators"]')).toContainText(username);
  }

  async selectBrainRegion(regionId: string) {
    await this.page.click(`[data-brain-region="${regionId}"]`);
  }

  async addBrainAnnotation(regionId: string, annotation: string) {
    await this.selectBrainRegion(regionId);
    await this.page.click('[data-testid="add-annotation-button"]');
    await this.page.fill('[data-testid="annotation-input"]', annotation);
    await this.page.click('[data-testid="save-annotation"]');
  }
}

// Authentication helper
class AuthHelper {
  constructor(private page: Page) {}

  async login(email: string = TEST_CONFIG.defaultUser.email, password: string = TEST_CONFIG.defaultUser.password) {
    await this.page.goto(`${TEST_CONFIG.baseURL}/login`);
    await this.page.fill('[data-testid="email-input"]', email);
    await this.page.fill('[data-testid="password-input"]', password);
    await this.page.click('[data-testid="login-button"]');
    await this.page.waitForURL('**/dashboard');
  }

  async logout() {
    await this.page.click('[data-testid="user-menu"]');
    await this.page.click('[data-testid="logout-button"]');
  }
}

// Multi-browser test setup
async function createMultipleBrowserSessions(numSessions: number) {
  const sessions = [];

  for (let i = 0; i < numSessions; i++) {
    const browser = await chromium.launch();
    const context = await browser.newContext({
      viewport: { width: 1280, height: 720 }
    });
    const page = await context.newPage();

    sessions.push({
      browser,
      context,
      page,
      helper: new CollaborationHelper(page),
      auth: new AuthHelper(page)
    });
  }

  return sessions;
}

// Test suite setup
test.describe('Real-time Collaboration E2E Tests', () => {
  test.setTimeout(60000); // 60 second timeout for collaboration tests

  test.describe('Basic Collaboration Features', () => {
    test('user can see collaboration interface', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('test-document-1');
      await helper.waitForCollaborationFeatures();

      // Check presence indicator
      await expect(page.locator('[data-testid="presence-indicator"]')).toBeVisible();
      await expect(page.locator('[data-testid="user-count"]')).toContainText('1 user online');

      // Check action buttons
      await expect(page.locator('[data-testid="comments-button"]')).toBeVisible();
      await expect(page.locator('[data-testid="share-button"]')).toBeVisible();
    });

    test('user can add and view comments', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('test-document-1');
      await helper.waitForCollaborationFeatures();

      await helper.openCommentsPanel();

      // Add a comment
      const testComment = 'This is a test comment for E2E testing';
      await helper.addComment(testComment);

      // Verify comment appears
      await helper.waitForComment(testComment);
      await expect(page.locator(`text=${testComment}`)).toBeVisible();

      // Check comment count updated
      await expect(page.locator('[data-testid="comments-button"]')).toContainText('Comments (1)');
    });

    test('user can configure share settings', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('test-document-1');
      await helper.waitForCollaborationFeatures();

      await helper.openShareDialog();

      // Test visibility settings
      await helper.setShareVisibility('team');
      await expect(page.locator('[data-testid="visibility-team"]')).toBeChecked();

      // Test share link copying
      await helper.copyShareLink();
      await expect(page.locator('.toast')).toContainText('Link copied');

      // Save settings
      await page.click('[data-testid="save-share"]');
      await expect(page.locator('[data-testid="share-dialog"]')).not.toBeVisible();
    });
  });

  test.describe('Multi-User Collaboration', () => {
    test('multiple users can collaborate in real-time', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        // User 1 logs in and opens document
        await session1.auth.login('user1@test.com', 'password');
        await session1.helper.navigateToDocument('multi-user-test-doc');
        await session1.helper.waitForCollaborationFeatures();

        // User 2 logs in and opens same document
        await session2.auth.login('user2@test.com', 'password');
        await session2.helper.navigateToDocument('multi-user-test-doc');
        await session2.helper.waitForCollaborationFeatures();

        // User 1 should see User 2 join
        await session1.helper.waitForUserJoin();
        expect(await session1.helper.getUserCount()).toBe(2);

        // User 2 should also see 2 users
        expect(await session2.helper.getUserCount()).toBe(2);

        // Test real-time commenting
        await session1.helper.openCommentsPanel();
        await session2.helper.openCommentsPanel();

        const comment1 = 'Comment from User 1';
        await session1.helper.addComment(comment1);

        // User 2 should see the comment
        await session2.helper.waitForComment(comment1);
        await expect(session2.page.locator(`text=${comment1}`)).toBeVisible();

        // User 2 replies
        const comment2 = 'Reply from User 2';
        await session2.helper.addComment(comment2);

        // User 1 should see the reply
        await session1.helper.waitForComment(comment2);
        await expect(session1.page.locator(`text=${comment2}`)).toBeVisible();

      } finally {
        // Cleanup
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });

    test('cursor positions are synchronized between users', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        // Setup both users
        await session1.auth.login('user1@test.com', 'password');
        await session1.helper.navigateToDocument('cursor-sync-test');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('user2@test.com', 'password');
        await session2.helper.navigateToDocument('cursor-sync-test');
        await session2.helper.waitForCollaborationFeatures();

        // Wait for both users to be connected
        await session1.helper.waitForUserJoin();

        // User 1 moves cursor
        await session1.helper.simulateCursorMovement(300, 400);

        // User 2 should see User 1's cursor (with some delay for WebSocket)
        await session2.page.waitForTimeout(1000);

        // Look for collaborative cursor
        const cursor = await session2.page.locator('[data-testid^="cursor-"]').first();
        await expect(cursor).toBeVisible({ timeout: 5000 });

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });

    test('typing indicators work across users', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        // Setup users
        await session1.auth.login('user1@test.com', 'password');
        await session1.helper.navigateToDocument('typing-test');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('user2@test.com', 'password');
        await session2.helper.navigateToDocument('typing-test');
        await session2.helper.waitForCollaborationFeatures();

        // Open comments on both
        await session1.helper.openCommentsPanel();
        await session2.helper.openCommentsPanel();

        // User 1 starts typing
        await session1.page.click('[data-testid="comment-input"]');
        await session1.page.type('[data-testid="comment-input"]', 'Typing', { delay: 100 });

        // User 2 should see typing indicator
        await session2.helper.waitForTypingIndicator('User 1');

        // Stop typing and indicator should disappear
        await session1.page.waitForTimeout(2000); // Wait for typing timeout
        await expect(session2.page.locator('[data-testid="typing-indicators"]')).not.toBeVisible({ timeout: 5000 });

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });
  });

  test.describe('Brain Annotation Collaboration', () => {
    test('multiple users can collaboratively annotate brain regions', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        // Setup users in brain analysis document
        await session1.auth.login('researcher1@test.com', 'password');
        await session1.helper.navigateToDocument('brain-analysis-doc');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('researcher2@test.com', 'password');
        await session2.helper.navigateToDocument('brain-analysis-doc');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // User 1 adds brain region annotation
        await session1.helper.addBrainAnnotation('prefrontal-cortex', 'Increased activation in working memory task');

        // User 2 should see the annotation
        await session2.page.waitForSelector('[data-annotation="prefrontal-cortex"]', { timeout: 10000 });
        await expect(session2.page.locator('[data-annotation="prefrontal-cortex"]')).toBeVisible();

        // User 2 adds annotation to different region
        await session2.helper.addBrainAnnotation('visual-cortex', 'Strong response to visual stimuli');

        // User 1 should see User 2's annotation
        await session1.page.waitForSelector('[data-annotation="visual-cortex"]', { timeout: 10000 });
        await expect(session1.page.locator('[data-annotation="visual-cortex"]')).toBeVisible();

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });

    test('collaborative statistical threshold adjustments', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        await session1.auth.login('analyst1@test.com', 'password');
        await session1.helper.navigateToDocument('stats-analysis-doc');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('analyst2@test.com', 'password');
        await session2.helper.navigateToDocument('stats-analysis-doc');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // User 1 adjusts statistical threshold
        await session1.page.click('[data-testid="threshold-control"]');
        await session1.page.fill('[data-testid="p-value-input"]', '0.001');
        await session1.page.selectOption('[data-testid="correction-select"]', 'fdr');
        await session1.page.click('[data-testid="apply-threshold"]');

        // User 2 should see the threshold change reflected
        await session2.page.waitForFunction(() => {
          const pValueInput = document.querySelector('[data-testid="p-value-input"]') as HTMLInputElement;
          return pValueInput && pValueInput.value === '0.001';
        });

        const correctionSelect = session2.page.locator('[data-testid="correction-select"]');
        await expect(correctionSelect).toHaveValue('fdr');

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });
  });

  test.describe('Conflict Resolution', () => {
    test('handles simultaneous edits gracefully', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        await session1.auth.login('editor1@test.com', 'password');
        await session1.helper.navigateToDocument('edit-conflict-test');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('editor2@test.com', 'password');
        await session2.helper.navigateToDocument('edit-conflict-test');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // Both users try to edit the same element simultaneously
        const editableElement = '[data-testid="editable-content"]';

        await Promise.all([
          session1.page.click(editableElement),
          session2.page.click(editableElement)
        ]);

        await Promise.all([
          session1.page.type(editableElement, 'Edit from User 1'),
          session2.page.type(editableElement, 'Edit from User 2')
        ]);

        // Wait for conflict resolution
        await session1.page.waitForTimeout(2000);
        await session2.page.waitForTimeout(2000);

        // One of the edits should be preserved (operational transformation)
        const finalContent1 = await session1.page.textContent(editableElement);
        const finalContent2 = await session2.page.textContent(editableElement);

        // Content should be the same on both sessions after conflict resolution
        expect(finalContent1).toBe(finalContent2);

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });

    test('resolves annotation conflicts', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        await session1.auth.login('annotator1@test.com', 'password');
        await session1.helper.navigateToDocument('annotation-conflict-test');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('annotator2@test.com', 'password');
        await session2.helper.navigateToDocument('annotation-conflict-test');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // Both users try to annotate the same brain region simultaneously
        await Promise.all([
          session1.helper.addBrainAnnotation('hippocampus', 'Memory consolidation area'),
          session2.helper.addBrainAnnotation('hippocampus', 'Learning and memory region')
        ]);

        // Check that conflict is resolved - either both annotations exist or one is preserved
        await session1.page.waitForTimeout(3000);

        const annotations1 = await session1.page.locator('[data-annotation="hippocampus"]').count();
        const annotations2 = await session2.page.locator('[data-annotation="hippocampus"]').count();

        // Should have consistent state across both sessions
        expect(annotations1).toBe(annotations2);
        expect(annotations1).toBeGreaterThan(0);

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });
  });

  test.describe('Error Handling and Recovery', () => {
    test('handles WebSocket disconnection and reconnection', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('connection-test-doc');
      await helper.waitForCollaborationFeatures();

      // Verify initial connection
      await expect(page.locator('[data-testid="connection-status"]')).toContainText('Connected');

      // Simulate network disconnection by blocking WebSocket requests
      await page.route('ws://localhost:8000/**', route => route.abort());

      // Wait for disconnection to be detected
      await expect(page.locator('[data-testid="connection-status"]')).toContainText('Disconnected', { timeout: 10000 });

      // Re-enable WebSocket connections
      await page.unroute('ws://localhost:8000/**');

      // Should automatically reconnect
      await expect(page.locator('[data-testid="connection-status"]')).toContainText('Connected', { timeout: 15000 });
    });

    test('gracefully handles malformed WebSocket messages', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('malformed-message-test');
      await helper.waitForCollaborationFeatures();

      // Inject malformed WebSocket message handling test
      await page.evaluate(() => {
        const ws = (window as any).collaborationWebSocket;
        if (ws) {
          // Simulate receiving malformed message
          ws.dispatchEvent(new MessageEvent('message', {
            data: 'invalid json {'
          }));
        }
      });

      // Application should still be functional
      await helper.openCommentsPanel();
      await helper.addComment('Test comment after malformed message');
      await helper.waitForComment('Test comment after malformed message');

      await expect(page.locator('text=Test comment after malformed message')).toBeVisible();
    });

    test('handles user permissions and access control', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [ownerSession, viewerSession] = sessions;

      try {
        // Owner logs in
        await ownerSession.auth.login('owner@test.com', 'password');
        await ownerSession.helper.navigateToDocument('permission-test-doc');
        await ownerSession.helper.waitForCollaborationFeatures();

        // Viewer logs in (limited permissions)
        await viewerSession.auth.login('viewer@test.com', 'password');
        await viewerSession.helper.navigateToDocument('permission-test-doc');
        await viewerSession.helper.waitForCollaborationFeatures();

        await ownerSession.helper.waitForUserJoin();

        // Owner can add comments
        await ownerSession.helper.openCommentsPanel();
        await ownerSession.helper.addComment('Comment from owner');

        // Viewer can see comments but might have limited editing capabilities
        await viewerSession.helper.openCommentsPanel();
        await viewerSession.helper.waitForComment('Comment from owner');

        // Check if viewer has appropriate UI restrictions
        const viewerEditButton = viewerSession.page.locator('[data-testid="edit-document-button"]');
        await expect(viewerEditButton).not.toBeVisible();

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });

    test('handles high-frequency updates without performance degradation', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        await session1.auth.login('speed1@test.com', 'password');
        await session1.helper.navigateToDocument('performance-test-doc');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('speed2@test.com', 'password');
        await session2.helper.navigateToDocument('performance-test-doc');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // Start performance monitoring
        const startTime = Date.now();

        // Simulate rapid cursor movements
        for (let i = 0; i < 50; i++) {
          await session1.helper.simulateCursorMovement(i * 10, i * 5);
          await session1.page.waitForTimeout(20); // 20ms between moves
        }

        const endTime = Date.now();
        const totalTime = endTime - startTime;

        // Should handle rapid updates efficiently (less than 5 seconds for 50 updates)
        expect(totalTime).toBeLessThan(5000);

        // Both sessions should still be responsive
        await session1.helper.openCommentsPanel();
        await session1.helper.addComment('Performance test completed');

        await session2.helper.openCommentsPanel();
        await session2.helper.waitForComment('Performance test completed');

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });
  });

  test.describe('Cross-Browser Compatibility', () => {
    test('collaboration works across different browsers', async () => {
      const chromiumBrowser = await chromium.launch();
      const firefoxBrowser = await firefox.launch();

      const chromiumContext = await chromiumBrowser.newContext();
      const firefoxContext = await firefoxBrowser.newContext();

      const chromiumPage = await chromiumContext.newPage();
      const firefoxPage = await firefoxContext.newPage();

      const chromiumHelper = new CollaborationHelper(chromiumPage);
      const firefoxHelper = new CollaborationHelper(firefoxPage);

      const chromiumAuth = new AuthHelper(chromiumPage);
      const firefoxAuth = new AuthHelper(firefoxPage);

      try {
        // Chromium user
        await chromiumAuth.login('chromium@test.com', 'password');
        await chromiumHelper.navigateToDocument('cross-browser-test');
        await chromiumHelper.waitForCollaborationFeatures();

        // Firefox user
        await firefoxAuth.login('firefox@test.com', 'password');
        await firefoxHelper.navigateToDocument('cross-browser-test');
        await firefoxHelper.waitForCollaborationFeatures();

        // Wait for users to see each other
        await chromiumHelper.waitForUserJoin();

        // Test cross-browser commenting
        await chromiumHelper.openCommentsPanel();
        await firefoxHelper.openCommentsPanel();

        await chromiumHelper.addComment('Comment from Chromium');
        await firefoxHelper.waitForComment('Comment from Chromium');

        await firefoxHelper.addComment('Reply from Firefox');
        await chromiumHelper.waitForComment('Reply from Firefox');

        // Both comments should be visible in both browsers
        await expect(chromiumPage.locator('text=Comment from Chromium')).toBeVisible();
        await expect(chromiumPage.locator('text=Reply from Firefox')).toBeVisible();
        await expect(firefoxPage.locator('text=Comment from Chromium')).toBeVisible();
        await expect(firefoxPage.locator('text=Reply from Firefox')).toBeVisible();

      } finally {
        await chromiumContext.close();
        await firefoxContext.close();
        await chromiumBrowser.close();
        await firefoxBrowser.close();
      }
    });
  });

  test.describe('Accessibility in Collaboration', () => {
    test('collaboration features are accessible via keyboard', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('accessibility-test-doc');
      await helper.waitForCollaborationFeatures();

      // Test keyboard navigation through collaboration controls
      await page.keyboard.press('Tab'); // Focus comments button
      await expect(page.locator('[data-testid="comments-button"]')).toBeFocused();

      await page.keyboard.press('Enter'); // Open comments
      await expect(page.locator('[data-testid="comments-panel"]')).toBeVisible();

      // Navigate to comment input via keyboard
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      await expect(page.locator('[data-testid="comment-input"]')).toBeFocused();

      // Add comment via keyboard
      await page.keyboard.type('Keyboard accessibility test comment');
      await page.keyboard.press('Enter');

      // Comment should be added
      await helper.waitForComment('Keyboard accessibility test comment');
    });

    test('screen reader announcements for collaboration events', async ({ page }) => {
      const helper = new CollaborationHelper(page);
      const auth = new AuthHelper(page);

      await auth.login();
      await helper.navigateToDocument('screen-reader-test-doc');
      await helper.waitForCollaborationFeatures();

      // Check for aria-live regions for dynamic updates
      await expect(page.locator('[aria-live="polite"]')).toBeAttached();

      // Add a comment and check for accessibility announcements
      await helper.openCommentsPanel();
      await helper.addComment('Accessibility test comment');

      // Should have accessible content for screen readers
      await expect(page.locator('[role="log"]')).toBeAttached(); // For comment feed
    });
  });

  test.describe('State Synchronization', () => {
    test('document state is synchronized after user reconnection', async () => {
      const sessions = await createMultipleBrowserSessions(2);
      const [session1, session2] = sessions;

      try {
        // Both users connect initially
        await session1.auth.login('sync1@test.com', 'password');
        await session1.helper.navigateToDocument('sync-test-doc');
        await session1.helper.waitForCollaborationFeatures();

        await session2.auth.login('sync2@test.com', 'password');
        await session2.helper.navigateToDocument('sync-test-doc');
        await session2.helper.waitForCollaborationFeatures();

        await session1.helper.waitForUserJoin();

        // User 1 adds some content while User 2 is connected
        await session1.helper.openCommentsPanel();
        await session1.helper.addComment('Comment while connected');

        await session2.helper.openCommentsPanel();
        await session2.helper.waitForComment('Comment while connected');

        // Simulate User 2 disconnecting
        await session2.page.evaluate(() => {
          // Close WebSocket connection
          const ws = (window as any).collaborationWebSocket;
          if (ws) ws.close();
        });

        // User 1 adds more content while User 2 is disconnected
        await session1.helper.addComment('Comment while disconnected');

        // User 2 reconnects (reload page)
        await session2.page.reload();
        await session2.helper.waitForCollaborationFeatures();
        await session2.helper.openCommentsPanel();

        // User 2 should see all comments after reconnection
        await session2.helper.waitForComment('Comment while connected');
        await session2.helper.waitForComment('Comment while disconnected');

      } finally {
        for (const session of sessions) {
          await session.context.close();
          await session.browser.close();
        }
      }
    });
  });
});

// Performance and load testing
test.describe('Collaboration Performance Tests', () => {
  test('handles multiple concurrent users efficiently', async () => {
    const numUsers = 5;
    const sessions = await createMultipleBrowserSessions(numUsers);

    try {
      const documentId = 'load-test-doc';

      // Connect all users
      for (let i = 0; i < numUsers; i++) {
        await sessions[i].auth.login(`loadtest${i}@test.com`, 'password');
        await sessions[i].helper.navigateToDocument(documentId);
        await sessions[i].helper.waitForCollaborationFeatures();
      }

      // Wait for all users to see each other
      for (const session of sessions) {
        await session.helper.waitForUserJoin();
      }

      // All users should see the correct user count
      for (const session of sessions) {
        expect(await session.helper.getUserCount()).toBe(numUsers);
      }

      // Test concurrent commenting
      const startTime = Date.now();

      const commentPromises = sessions.map(async (session, index) => {
        await session.helper.openCommentsPanel();
        await session.helper.addComment(`Concurrent comment from User ${index + 1}`);
      });

      await Promise.all(commentPromises);

      const endTime = Date.now();
      const totalTime = endTime - startTime;

      // Should handle concurrent operations efficiently
      expect(totalTime).toBeLessThan(10000); // Less than 10 seconds

      // All users should see all comments
      for (const session of sessions) {
        for (let i = 0; i < numUsers; i++) {
          await session.helper.waitForComment(`Concurrent comment from User ${i + 1}`);
        }
      }

    } finally {
      for (const session of sessions) {
        await session.context.close();
        await session.browser.close();
      }
    }
  });
});
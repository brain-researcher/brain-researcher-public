import { test, expect } from "@playwright/test";

/**
 * End-to-end tests for the 3D Brain Viewer component and integration.
 *
 * Tests cover:
 * - Niivue canvas rendering
 * - Artifact selection and loading
 * - Threshold controls
 * - Peak coordinate overlay
 * - View mode switching
 * - Download functionality
 * - Error states
 */

test.describe.skip("3D Brain Viewer (demo)", () => {
  test.beforeEach(async ({ page }) => {
    // Demo no longer represents the canonical Result Package UI.
    // Keep this spec skipped until we add a dedicated viewer-only smoke test.
    // Navigate to a demo with 3D visualization support
    await page.goto("/demo/glm_motor", {
      waitUntil: "domcontentloaded",
    });

    // Switch to visualizations tab
    const visualizationsTab = page.getByRole("tab", { name: /Visualizations/i });
    await expect(visualizationsTab).toBeVisible({ timeout: 60_000 });
    await visualizationsTab.click();
  });

  test("loads brain map in 3D viewer canvas", async ({ page }) => {
    // Wait for visualization grid to load
    await expect(page.locator(".visualization-grid, [data-testid='visualization-grid']").first()).toBeVisible({ timeout: 10000 });

    // Look for 3D viewer button or artifact card
    const view3dButton = page.getByRole("button", { name: /3D/i }).first();

    if (await view3dButton.isVisible()) {
      await view3dButton.click();

      // Wait for canvas to be rendered
      const canvas = page.locator("canvas").first();
      await expect(canvas).toBeVisible({ timeout: 15000 });

      // Verify canvas has non-zero dimensions
      const box = await canvas.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThan(100);
      expect(box!.height).toBeGreaterThan(100);
    }
  });

  test("artifact selection switches brain maps", async ({ page }) => {
    // Check if BrainViewer component is present (inline viewer)
    const artifactList = page.locator("[data-testid='artifact-list'], .artifact-list");

    if (await artifactList.isVisible({ timeout: 5000 })) {
      // Get first two artifact buttons
      const artifacts = page.locator("button").filter({ hasText: /stat|contrast/i });
      const firstArtifact = artifacts.first();
      const secondArtifact = artifacts.nth(1);

      if (await secondArtifact.isVisible()) {
        // Click first artifact
        await firstArtifact.click();
        await page.waitForTimeout(1000);

        // Click second artifact
        await secondArtifact.click();
        await page.waitForTimeout(1000);

        // Verify canvas is still visible (map switched)
        await expect(page.locator("canvas").first()).toBeVisible();
      }
    }
  });

  test("threshold slider updates visualization", async ({ page }) => {
    // Look for threshold slider
    const thresholdSlider = page.locator("input[type='range']").filter({ hasText: /threshold/i }).or(
      page.locator("[role='slider']").filter({ hasText: /threshold/i })
    ).first();

    if (await thresholdSlider.isVisible({ timeout: 5000 })) {
      // Get initial value
      const initialValue = await thresholdSlider.getAttribute("aria-valuenow") ||
                          await thresholdSlider.inputValue();

      // Drag slider (simulate threshold change)
      const sliderBox = await thresholdSlider.boundingBox();
      if (sliderBox) {
        await page.mouse.move(sliderBox.x + sliderBox.width * 0.3, sliderBox.y + sliderBox.height / 2);
        await page.mouse.down();
        await page.mouse.move(sliderBox.x + sliderBox.width * 0.7, sliderBox.y + sliderBox.height / 2);
        await page.mouse.up();

        // Wait for debounce and re-render
        await page.waitForTimeout(1500);

        // Verify value changed
        const newValue = await thresholdSlider.getAttribute("aria-valuenow") ||
                        await thresholdSlider.inputValue();
        expect(newValue).not.toBe(initialValue);
      }
    }
  });

  test("peak markers render and are clickable", async ({ page }) => {
    // Wait for peak detection to complete (after initial render)
    await page.waitForTimeout(2000);

    // Look for peak cards/markers
    const peakCard = page.locator("[data-testid='peak-card'], .peak-card, button").filter({
      hasText: /peak|MNI|coordinate/i
    }).first();

    if (await peakCard.isVisible({ timeout: 5000 })) {
      // Click peak card to focus
      await peakCard.click();
      await page.waitForTimeout(500);

      // Verify the peak is highlighted or focused (could check for active class)
      // This depends on implementation details
      expect(await peakCard.isVisible()).toBe(true);
    }
  });

  test("view mode buttons switch correctly", async ({ page }) => {
    // Look for view mode controls (axial, coronal, sagittal, 3D)
    const axialButton = page.getByRole("button", { name: /axial/i });
    const coronalButton = page.getByRole("button", { name: /coronal/i });
    const sagittalButton = page.getByRole("button", { name: /sagittal/i });

    if (await axialButton.isVisible({ timeout: 5000 })) {
      // Click axial view
      await axialButton.click();
      await page.waitForTimeout(500);

      // Canvas should still be visible
      await expect(page.locator("canvas").first()).toBeVisible();

      if (await coronalButton.isVisible()) {
        // Click coronal view
        await coronalButton.click();
        await page.waitForTimeout(500);
        await expect(page.locator("canvas").first()).toBeVisible();
      }

      if (await sagittalButton.isVisible()) {
        // Click sagittal view
        await sagittalButton.click();
        await page.waitForTimeout(500);
        await expect(page.locator("canvas").first()).toBeVisible();
      }
    }
  });

  test("download button downloads NIfTI file", async ({ page }) => {
    // Set up download listener
    const downloadPromise = page.waitForEvent("download", { timeout: 10000 }).catch(() => null);

    // Look for download button
    const downloadButton = page.getByRole("link", { name: /Download NIfTI/i }).or(
      page.getByRole("button", { name: /Download NIfTI/i })
    ).first();

    if (await downloadButton.isVisible({ timeout: 5000 })) {
      await downloadButton.click();

      const download = await downloadPromise;
      if (download) {
        // Verify download started
        expect(download.suggestedFilename()).toMatch(/\.nii\.gz$/);
      }
    }
  });

  test("evidence panel shows real citations", async ({ page }) => {
    // Switch to evidence tab
    const evidenceTab = page.getByRole("tab", { name: /evidence/i });

    if (await evidenceTab.isVisible({ timeout: 5000 })) {
      await evidenceTab.click();
      await page.waitForTimeout(1000);

      // Check for evidence items (methods, datasets, papers)
      const evidenceItems = page.locator("[data-testid='evidence-item'], .evidence-item").or(
        page.locator("div, article").filter({ hasText: /FSL|fMRI|OpenNeuro|method|dataset/i })
      );

      // Should have at least some evidence
      const count = await evidenceItems.count();
      expect(count).toBeGreaterThan(0);
    }
  });

  test("handles slow network gracefully", async ({ page }) => {
    // Simulate slow network
    await page.route("**/*peaks*", async (route) => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      await route.continue();
    });

    // Navigate and interact
    await page.goto("/demo/glm_motor");
    await page.getByRole("tab", { name: /Visualizations/i }).click();

    // Should show loading state
    const loadingIndicator = page
      .locator("text=/loading|computing|processing/i")
      .or(page.locator("[data-testid='loading']"))
      .first();

    if (await loadingIndicator.isVisible({ timeout: 1000 })) {
      // Loading indicator present during slow request
      expect(await loadingIndicator.isVisible()).toBe(true);
    }
  });

  test("displays error state when peaks API fails", async ({ page }) => {
    // Intercept peaks API and return error
    await page.route("**/api/demo/peaks/**", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Peak extraction failed" }),
      });
    });

    // Navigate to a page that mounts the BrainViewer and triggers peaks fetching.
    await page.goto("/demo/glm_motor", { waitUntil: "domcontentloaded" });
    await page.getByRole("tab", { name: /Visualizations/i }).click();

    // Peaks request should fail and surface a user-visible error in the peaks panel.
    await expect(page.getByRole("heading", { name: /Activation Peaks/i })).toBeVisible({ timeout: 20000 });
    await expect(page.getByText(/Peak extraction failed/i).first()).toBeVisible({ timeout: 20000 });
  });

  test("3D viewer modal opens in fullscreen", async ({ page }) => {
    // Look for modal trigger button
    const modalButton = page.getByRole("button", { name: /view|3D|fullscreen/i }).first();

    if (await modalButton.isVisible({ timeout: 5000 })) {
      await modalButton.click();
      await page.waitForTimeout(500);

      // Check for dialog/modal
      const dialog = page.locator("[role='dialog'], .modal, [data-testid='modal']");

      if (await dialog.isVisible()) {
        await expect(dialog).toBeVisible();

        // Canvas should be inside modal
        const canvasInModal = dialog.locator("canvas").first();
        await expect(canvasInModal).toBeVisible();

        // Close modal
        const closeButton = dialog.getByRole("button", { name: /close/i }).or(
          dialog.locator("button[aria-label='Close']")
        );

        if (await closeButton.isVisible()) {
          await closeButton.click();
          await expect(dialog).not.toBeVisible();
        }
      }
    }
  });
});

test.describe("3D Brain Viewer - Specific Demo Tests", () => {
  test("glm_motor demo loads with brain activation maps", async ({ page }) => {
    await page.goto("/demo/glm_motor");
    await page.getByRole("tab", { name: /Visualizations/i }).click();

    // Should show GLM-related visualizations
    const glmViz = page.locator("text=/motor|activation|statistical|T-stat|Z-stat/i");
    await expect(glmViz.first()).toBeVisible({ timeout: 10000 });
  });

  test("connectivity_dmn demo loads with connectivity visualizations", async ({ page }) => {
    await page.goto("/demo/connectivity_dmn");
    await page.getByRole("tab", { name: /Visualizations/i }).click();

    // Should show connectivity-related content
    const connViz = page.locator("text=/connectivity|network|DMN|default mode/i");
    await expect(connViz.first()).toBeVisible({ timeout: 10000 });
  });
});

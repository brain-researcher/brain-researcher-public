import { test, expect } from '@playwright/test';

test.describe.skip('Demo 3D viewer (demo)', () => {
  // Demo pages now render Result Package UI; 3D viewer coverage will move to a dedicated smoke test.
  test('loads base template and overlays without Niivue errors', async ({ page }) => {
    const demoUrl = '/demo/connectivity_dmn?mode=guided&src=cta';

    await page.goto(demoUrl, { waitUntil: 'domcontentloaded' });

    const visualizationsTab = page.getByRole('tab', { name: 'Visualizations' });
    await expect(visualizationsTab).toBeVisible({ timeout: 60_000 });

    // Guard against hydration races: retry until the tab is actually selected.
    await expect(async () => {
      await visualizationsTab.click();
      await expect(visualizationsTab).toHaveAttribute('aria-selected', 'true');
    }).toPass({ timeout: 45_000 });

    const view3dButton = page.getByRole('button', { name: /View.*in 3D|3D/i }).first();
    await expect(view3dButton).toBeVisible({ timeout: 60_000 });
    await view3dButton.click();

    await page.waitForFunction(() => {
      const win = window as unknown as {
        __NIIVUE_LAST_INSTANCE?: any;
        __BRAIN3D_LAST_ERROR?: any;
      };
      const nv = win.__NIIVUE_LAST_INSTANCE;
      if (!nv) return false;
      const overlays = Array.isArray(nv.volumes) ? nv.volumes.length : 0;
      const hasBase = Boolean((nv as any).back || (overlays > 0 && nv.volumes[0]));
      return hasBase && overlays >= 1 && !win.__BRAIN3D_LAST_ERROR;
    }, { timeout: 20000 });

    const viewerState = await page.evaluate(() => {
      const win = window as unknown as {
        __NIIVUE_LAST_INSTANCE?: any;
        __BRAIN3D_LAST_ERROR?: any;
        __BRAIN3D_LAST_LOAD?: any;
      };
      const nv = win.__NIIVUE_LAST_INSTANCE;
      return {
        hasInstance: !!nv,
        backgroundName: nv?.back?.name ?? nv?.volumes?.[0]?.name ?? null,
        overlayCount: nv?.volumes?.length ?? 0,
        canvas: {
          width: nv?.gl?.canvas?.width ?? nv?.canvas?.width ?? 0,
          height: nv?.gl?.canvas?.height ?? nv?.canvas?.height ?? 0,
        },
        lastError: win.__BRAIN3D_LAST_ERROR ?? null,
        lastLoad: win.__BRAIN3D_LAST_LOAD ?? null,
      };
    });

    expect(viewerState.hasInstance).toBeTruthy();
    expect(viewerState.lastError).toBeNull();
    expect(viewerState.backgroundName).not.toBeNull();
    expect(viewerState.overlayCount).toBeGreaterThan(0);
    expect(viewerState.canvas.width).toBeGreaterThan(0);
    expect(viewerState.canvas.height).toBeGreaterThan(0);
  });
});

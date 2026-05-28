# 3D Brain Viewer Testing Guide

This document provides manual testing procedures for the 3D Brain Viewer (UI-044) implementation.

## Prerequisites

1. **Start all services:**
   ```bash
   # From project root
   br serve agent
   br serve kg

   # In a third terminal, start the web UI
   br serve web

   # Or run the Next.js dev server directly
   cd apps/web-ui
   npm install
   npm run dev
   ```

2. **Verify demo data exists:**
   ```bash
   # Check that demo artifacts are present
   ls data/openneuro_glmfitlins/stat_maps/ds000009/
   ```

3. **Open browser:**
   - Navigate to `http://localhost:3000`

## Manual Test Checklist

### Test 1: GLM Motor Demo - Basic 3D Viewer

**URL:** `http://localhost:3000/demo/glm_motor`

- [ ] Page loads without errors
- [ ] Click "Visualizations" tab
- [ ] Verify brain map thumbnails are displayed (not placeholder images)
- [ ] Click first thumbnail or "3D" button
- [ ] **3D viewer canvas renders** with brain overlay
- [ ] Brain activation map is visible (colored overlay on anatomical)
- [ ] No console errors in browser DevTools

### Test 2: Threshold Controls

**Continuing from Test 1:**

- [ ] Locate threshold slider (labeled with current value)
- [ ] Drag slider to increase threshold (e.g., from 2.3 to 4.0)
- [ ] Visualization updates after ~500ms (debounced)
- [ ] Colored activation areas shrink (higher threshold = fewer voxels)
- [ ] Drag slider to decrease threshold
- [ ] Activation areas expand
- [ ] No flickering or performance issues

### Test 3: Opacity Controls

- [ ] Locate opacity slider
- [ ] Set opacity to 0.5
- [ ] Overlay becomes semi-transparent (can see anatomical underneath)
- [ ] Set opacity to 1.0
- [ ] Overlay fully opaque
- [ ] Set opacity to 0.1
- [ ] Overlay barely visible

### Test 4: View Mode Switching

- [ ] Click "Axial" view button
- [ ] Canvas updates to show horizontal slices
- [ ] Crosshair visible in center
- [ ] Click "Coronal" view button
- [ ] View changes to front-back slices
- [ ] Click "Sagittal" view button
- [ ] View changes to left-right slices
- [ ] Click "3D" view button
- [ ] Returns to 3D render mode
- [ ] Click "Mosaic" button (if available)
- [ ] Shows multiple slices in grid

### Test 5: Peak Coordinate Overlay

**Check for peak detection:**

- [ ] Below the 3D viewer, peaks section is visible
- [ ] Status shows "Recomputing peaks…" briefly after threshold change
- [ ] Peak cards display with:
  - Peak number (Peak 1, Peak 2, etc.)
  - Statistical value (e.g., Z = 5.2)
  - MNI coordinates (x, y, z)
  - Cluster size
- [ ] Click on first peak card
- [ ] Crosshair jumps to that coordinate in 3D viewer
- [ ] Click on second peak
- [ ] Crosshair jumps again
- [ ] Adjust threshold slider high (e.g., 10.0)
- [ ] Message shows "No peaks above the current threshold"
- [ ] Reduce threshold back to default
- [ ] Peaks reappear

### Test 6: Artifact Selection

**If inline BrainViewer is available:**

- [ ] Artifact list shows multiple statistical maps
- [ ] Each artifact shows:
  - Subject ID (if applicable)
  - Contrast name
  - Statistic type (T, Z, F)
- [ ] Click different artifact
- [ ] 3D viewer loads new brain map
- [ ] Peaks recalculate for new map
- [ ] Threshold resets to default for new stat type

### Test 7: Download Functionality

- [ ] Click "Download" button/link next to artifact
- [ ] Browser downloads `.nii.gz` file
- [ ] File size > 0 bytes (not empty)
- [ ] Filename matches artifact ID

### Test 8: Evidence Integration

- [ ] Click "Evidence" tab
- [ ] Evidence items are displayed (NOT placeholders)
- [ ] Should see:
  - Method evidence (e.g., "FSL FEAT Pipeline")
  - Dataset evidence (e.g., "OpenNeuro ds000009")
  - Validation or paper references (if available)
- [ ] Each evidence item has:
  - Title
  - Description
  - Source
  - Relevance score or metadata

### Test 9: Loading & Error States

**Test loading state:**

- [ ] Open Network tab in DevTools
- [ ] Set throttling to "Slow 3G"
- [ ] Reload page
- [ ] See loading skeleton or spinner for visualizations
- [ ] "Loading 3D viewer…" message appears
- [ ] Canvas eventually renders when data arrives

**Test error handling:**

- [ ] Open Network tab
- [ ] Block request to `/api/demo/peaks/*` (set to fail/404)
- [ ] Error message appears: "Failed to extract peaks" or similar
- [ ] Viewer still shows brain map (degrades gracefully)
- [ ] Retry button or reload allows recovery

### Test 10: Connectivity DMN Demo

**URL:** `http://localhost:3000/demo/connectivity_dmn`

- [ ] Page loads
- [ ] Click "Visualizations" tab
- [ ] Connectivity matrix or network visualizations shown
- [ ] If 3D brain maps available, test same controls as Test 1-7

### Test 11: Group Analysis Demo

**URL:** `http://localhost:3000/demo/group_analysis`

- [ ] Page loads
- [ ] Shows group-level results
- [ ] Visualizations tab has brain maps
- [ ] Test 3D viewer if available

### Test 12: Meta-analysis Demo

**URL:** `http://localhost:3000/demo/meta_analysis`

- [ ] Page loads
- [ ] Shows meta-analysis query results
- [ ] Visualizations or evidence displayed

### Test 13: Smart Preprocessing Demo

**URL:** `http://localhost:3000/demo/smart_preprocessing`

- [ ] Page loads
- [ ] QC visualizations or preprocessing summary shown
- [ ] No broken images or missing data

## Performance Checks

- [ ] **Page Load Time:** < 3 seconds for initial render
- [ ] **3D Viewer Init:** < 5 seconds to show brain
- [ ] **Threshold Slider:** Smooth dragging, no lag
- [ ] **Peak Recalculation:** < 2 seconds after threshold change
- [ ] **View Switching:** Instant (<500ms)
- [ ] **Memory:** No memory leaks after multiple interactions (check DevTools Performance tab)

## Browser Compatibility

Test in at least 2 browsers:

- [ ] Chrome/Edge (latest)
- [ ] Firefox (latest)
- [ ] Safari (if available)

## Mobile Responsiveness (Optional)

- [ ] Open on mobile device or use DevTools mobile emulation
- [ ] Visualizations tab accessible
- [ ] 3D viewer renders (may have reduced performance)
- [ ] Touch controls work for dragging/zooming

## Common Issues & Debugging

### Issue: "No artifacts available"

**Solution:**
- Check that demo data exists in `data/openneuro_glmfitlins/`
- Verify the backend serving `/api/demo/*` is running
- Check agent/orchestrator logs for errors

### Issue: Canvas is blank/black

**Solution:**
- Open browser console, check for WebGL errors
- Verify NIfTI files are accessible at `/api/demo/artifacts/...`
- Check Network tab for 404 errors on volume loading

### Issue: Peaks not loading

**Solution:**
- Verify peaks API endpoint responds: `http://localhost:3000/api/demo/peaks/glm_motor/sub-01_stat-z_statmap.nii.gz?threshold=2.3`
- Check agent/orchestrator logs for peak extraction errors
- Verify `scipy` and `nibabel` are installed in the backend environment

### Issue: Evidence shows placeholders

**Solution:**
- Check if evidence API returns real data: `http://localhost:3000/api/demo/real-evidence/glm_motor`
- Look for console warning: "[DemoResultDisplay] Using placeholder visualizations..."
- Verify demo data generation has completed

## Automated Tests

Run automated tests to complement manual testing:

```bash
# Contract tests (Pact)
pytest tests/contracts/consumers/test_webui_orchestrator_contract.py::TestWebUIToOrchestratorContract::test_get_demo_peaks_contract -v

# E2E tests (Playwright)
cd apps/web-ui
npx playwright test tests/e2e/3d-brain-viewer.spec.ts

# Run all E2E tests
npx playwright test

# Run with UI for debugging
npx playwright test --ui
```

## Sign-off Criteria

All tests pass when:

✅ All manual checklist items completed
✅ No console errors during normal operation
✅ All demos load successfully
✅ 3D viewer renders brain maps correctly
✅ Peaks API returns valid coordinates
✅ Evidence shows real data (not placeholders)
✅ Contract tests pass
✅ E2E tests pass

## Reporting Issues

If you find issues during testing:

1. **Check console for errors** (F12 → Console tab)
2. **Check Network tab** for failed requests
3. **Note reproduction steps**
4. **Take screenshot** if visual issue
5. **Create GitHub issue** with:
   - Browser & version
   - Steps to reproduce
   - Expected vs actual behavior
   - Console errors
   - Screenshots

---

**Last Updated:** 2025-01-17
**Test Coverage:** UI-044 - 3D Brain Viewer + Frontend Demo Page Wiring

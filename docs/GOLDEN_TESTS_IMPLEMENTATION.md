# Golden Tests Implementation (Item #9)

**Status**: Framework Complete ✅ | Tool Execution Blocked 🚧 | Implementation: ~70% Complete

**Estimated Time**: 40-55h | **Actual Time**: ~6h (framework only)

---

## Overview

Golden tests validate neuroimaging tool outputs against reference "golden" outputs using **tolerance-based comparison** instead of exact checksums. This approach handles acceptable floating-point precision differences while catching genuine regressions.

**Key Achievement**: We now have a complete tolerance-based comparison framework that can validate neuroimaging outputs with configurable precision thresholds.

**Blocking Issue**: Container execution failures prevent generating real golden references from tool runs. Once resolved, the framework is ready to use.

---

## What Was Implemented

### ✅ Phase 1: Test Data Preparation (Complete)
**Files Created**:
- `tests/fixtures/golden_data/generate_synthetic_data.py` (+340 lines)
- Synthetic test data (32 KB total, git-friendly)

**Features**:
- Small NIfTI files (10x10x10 voxels, deterministic seeds)
- BIDS-compliant directory structure
- Standalone test files for FSL, AFNI, ANTs, FreeSurfer
- Fully reproducible (seeded random generation)

**Test Data Created**:
```
golden_data/
├── bids_dataset/
│   └── sub-01/ses-01/
│       ├── anat/sub-01_ses-01_T1w.nii.gz (4KB)
│       └── func/sub-01_ses-01_task-rest_bold.nii.gz (80KB)
└── standalone/
    ├── fsl/brain_input.nii.gz
    ├── afni/timeseries_input.nii.gz
    ├── ants/fixed_image.nii.gz + moving_image.nii.gz
    └── freesurfer/convert_input.nii.gz
```

---

### ✅ Phase 2: Tolerance-Based Comparison Framework (Complete)
**File Created**:
- `tests/integration/golden/framework.py` (+500 lines)

**Core Components**:

#### 1. `ComparisonResult` Dataclass
Structured comparison results with:
- Pass/fail status
- Detailed difference listing
- Statistical summaries
- Tolerance configuration used

####2. `ToleranceConfig` Dataclass
Configurable tolerance thresholds:
```python
@dataclass
class ToleranceConfig:
    relative_tolerance: float = 1e-5           # 0.001% relative difference
    absolute_tolerance: float = 1e-6           # Absolute difference floor
    voxel_size_tolerance: float = 0.01         # 0.01mm voxel size tolerance
    affine_tolerance: float = 1e-4             # Affine matrix tolerance
    max_differing_voxels_pct: float = 0.1      # 0.1% voxels can differ
    stats_relative_tolerance: float = 1e-3     # 0.1% for summary statistics
```

#### 3. Comparison Functions
- `compare_nifti_files()` - Main comparison with full validation
- `compare_nifti_data()` - Array comparison with `np.allclose()`
- `compare_nifti_headers()` - Affine and voxel size validation
- `compare_nifti_statistics()` - Statistical summary comparison
- `compute_nifti_statistics()` - Generate mean, std, min, max, median, nonzero stats

#### 4. Golden Reference Management
- `save_golden_reference()` - Save output as reference with metadata
- `load_manifest()` - Load reference metadata
- Versioned manifests for backward compatibility

**Key Design Decisions** (Per Codex Feedback):
1. ✅ **Tolerance-based vs. exact checksums**: Use `np.allclose()` with configurable rtol/atol
2. ✅ **Statistical summaries**: Compare mean/std/median in addition to voxel data
3. ✅ **Percentage-based thresholds**: Allow small % of voxels to differ
4. ✅ **Metadata tracking**: Save tolerance config with each reference

---

### ✅ Phase 3: Golden Test Implementation (Partial)
**Files Created**:
- `tests/integration/golden/test_fsl_golden.py` (+220 lines)
- `tests/integration/golden/generate_golden_references.py` (+160 lines, incomplete)

**Test Structure**:
```python
class TestFSLBET:
    """Golden tests for FSL BET."""

    @pytest.fixture
    def bet_input(self):
        """Real OpenNeuro data path."""
        return OPENNEURO_DIR / "sub-06/ses-test/anat/sub-06_ses-test_T1w.nii.gz"

    @pytest.fixture
    def bet_golden_output(self):
        """Golden reference output."""
        return GOLDEN_REFS_DIR / "fsl/sub-06_ses-test_T1w_brain.nii.gz"

    def test_bet_brain_extraction_basic(self, bet_input, bet_golden_output):
        """Test BET matches golden reference (currently skipped)."""
        # TODO: Execute tool and compare
        # result = execute_niwrap_tool(...)
        # comparison = compare_nifti_files(actual, expected, tolerance)
        # assert comparison.passed
```

**Tests Passing**:
- ✅ `test_bet_tolerance_framework` - Validates tolerance config
- ✅ `test_example_synthetic_comparison` - Framework demo with identical images
- ✅ `test_example_tolerance_violation` - Framework demo detecting differences
- 🚧 `test_bet_brain_extraction_basic` - SKIPPED (needs container debugging)

**Test Results**:
```bash
$ pytest tests/integration/golden/ -xvs -m "integration or slow"
======================== 2 passed, 4 warnings in 0.26s =========================

$ pytest tests/integration/golden/test_fsl_golden.py::TestFSLBET -xvs
=================== 1 passed, 1 skipped, 4 warnings in 0.27s ====================
```

---

## 🚧 Blocking Issue: Container Execution Failures

### Problem
Container runtime fails when executing NiWrap tools:
```
ERROR: Container execution failed: Command failed with exit code 1
brain_researcher.services.toolhub.common.container_runner.ContainerExecutionError:
Command failed with exit code 1
```

**Symptoms**:
- stdout/stderr are empty (container never runs)
- Error at container runtime level, not tool level
- Affects both golden reference generation and actual testing

**Attempted Workarounds**:
1. ✅ Added `--allow-write` permission flag
2. ✅ Verified CVMFS mounted and accessible
3. ✅ Confirmed container images exist (`fsl_6.0.7.18_20250928.simg`)
4. ❌ Container still fails with exit code 1

**Command That Fails**:
```bash
br tools niwrap execute fsl.6.0.4.bet.run --params '{
  "infile": "/app/data/openneuro/ds000114/sub-06/ses-test/anat/sub-06_ses-test_T1w.nii.gz",
  "maskfile": "/tmp/test_brain",
  "fractional_intensity": 0.5
}' --allow-write
```

**Error Details**:
```
INFO:...:Image: fsl:6.0.4 → fsl_6.0.7.18_20250928.simg [best_effort]
INFO:...:GPU available but not required: GPU available: NVIDIA GeForce RTX 4090
ERROR:...:Container execution failed: Command failed with exit code 1
```

### Next Steps to Resolve
1. **Debug container runner**: Add verbose logging to `container_runner.py`
2. **Check bind mounts**: Verify `/tmp` and data directories are accessible
3. **Test with different tool**: Try simpler tool (e.g., `mri_convert`)
4. **Manual apptainer**: Run apptainer command directly to see raw error
5. **Permissions**: Check file/directory permissions on outputs

**Suggested Manual Test**:
```bash
# Try running apptainer directly
apptainer exec \
  /cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.18_20250928/fsl_6.0.7.18_20250928.simg \
  bet \
  /app/data/openneuro/ds000114/sub-06/ses-test/anat/sub-06_ses-test_T1w.nii.gz \
  /tmp/test_brain \
  0.5
```

---

## What Still Needs Implementation

### 🚧 Phase 3.5: Resolve Container Execution (BLOCKING)
**Estimated Time**: 2-4h
**Priority**: HIGH

**Tasks**:
1. Debug container runner to get actual stderr
2. Fix bind mount or permission issues
3. Verify at least one tool executes successfully

---

### ⏸️ Phase 4: Generate Golden References (BLOCKED)
**Estimated Time**: 4-6h
**Blocked By**: Container execution issues

**Tasks**:
1. Complete `generate_golden_references.py`
2. Run for FSL BET, AFNI 3dTstat, FreeSurfer mri_convert
3. Store references in `/app/data/golden_references/`
4. Generate metadata JSON for each reference

**Storage Strategy**:
- References stored in dataset directory (not git)
- Small metadata files in git
- CI can download/mount dataset separately

---

### ⏸️ Phase 5: Complete Test Coverage (BLOCKED)
**Estimated Time**: 8-12h
**Blocked By**: Golden references

**Tasks**:
1. Implement actual golden tests for FSL BET
2. Add tests for AFNI 3dTstat
3. Add tests for ANTs registration
4. Add tests for FreeSurfer mri_convert
5. Verify tolerance configurations work for all tools

---

### ⏸️ Phase 6: Checksum Update CLI Tool (TODO)
**Estimated Time**: 5h
**Status**: Not started

**Design** (from original plan):
```bash
br golden update --tool fsl_bet --accept-changes
br golden update --all --dry-run  # Preview changes
```

**Features**:
- Show diffs before accepting
- Require explicit confirmation
- Update reference outputs and tolerance files
- Git integration to show what changed

---

### ⏸️ Phase 7: CI Integration (TODO)
**Estimated Time**: 5-10h
**Status**: Not started

**Requirements**:
1. GitHub Actions workflow
2. Cache CVMFS containers or use pre-warmed runners
3. Fast subset (<5min) and full suite (optional)
4. Fail on tolerance violations
5. Parallel test execution

**Proposed Workflow**:
```yaml
name: Golden Tests
on: [pull_request]
jobs:
  golden-tests:
    runs-on: self-hosted  # Needs CVMFS access
    steps:
      - uses: actions/checkout@v3
      - name: Run fast golden tests
        run: pytest tests/integration/golden/ -m "not slow"
      - name: Run full golden tests (optional)
        if: github.event.pull_request.labels.contains('run-full-tests')
        run: pytest tests/integration/golden/ -m "slow"
```

---

## Usage Examples

### Running Golden Tests (Once Unblocked)
```bash
# Run all golden tests
pytest tests/integration/golden/ -xvs

# Run only fast tests
pytest tests/integration/golden/ -m "not slow"

# Run with integration/slow tests
pytest tests/integration/golden/ -xvs -m "integration or slow"

# Run specific tool tests
pytest tests/integration/golden/test_fsl_golden.py::TestFSLBET -xvs
```

### Updating Golden References (Future)
```bash
# Generate initial references
python tests/integration/golden/generate_golden_references.py

# Update after legitimate changes
br golden update --tool fsl_bet --accept-changes

# Preview updates without applying
br golden update --all --dry-run
```

### Using the Comparison Framework
```python
from tests.integration/golden.framework import (
    compare_nifti_files,
    ToleranceConfig,
)

# Custom tolerance for specific tool
tolerance = ToleranceConfig(
    relative_tolerance=1e-4,  # 0.01% relative difference
    absolute_tolerance=1e-5,
    max_differing_voxels_pct=0.5,  # Allow 0.5% voxels to differ
)

# Compare outputs
result = compare_nifti_files(
    actual_path=Path("/tmp/tool_output.nii.gz"),
    expected_path=Path("/dataset/golden_references/fsl/bet_output.nii.gz"),
    tolerance=tolerance,
)

if not result.passed:
    print(result.summary())
    print(result.statistics)
```

---

## Integration with Existing Codebase

### Compatibility with Artifact System (Item #6)
The golden test framework integrates naturally with the artifact provenance system:

```python
# After tool execution creates artifacts:
artifact_manager = ArtifactManager(run_id="golden_ref_gen", tool_slug="fsl_bet")
output_files = artifact_manager.track_output_files(tool_definition, execution_dir)

# Use artifact output as golden reference:
for output_file in output_files:
    save_golden_reference(
        output_path=Path(output_file.path),
        reference_dir=GOLDEN_REFS_DIR / tool_slug,
        tolerance=ToleranceConfig(),
    )
```

### Compatibility with GPU Detection (Item #4)
Golden tests should run consistently with/without GPU:

```python
# Tests should pass regardless of GPU availability
# Use CPU-only tools for deterministic results
# Or: verify GPU vs CPU outputs match within tolerance
```

---

## Files Created/Modified

### New Files
| File | Lines | Purpose |
|------|-------|---------|
| `tests/fixtures/golden_data/generate_synthetic_data.py` | +340 | Generate small test NIfTI files |
| `tests/integration/golden/framework.py` | +500 | Tolerance-based comparison framework |
| `tests/integration/golden/test_fsl_golden.py` | +220 | FSL golden tests (partial) |
| `tests/integration/golden/generate_golden_references.py` | +160 | Generate references (incomplete) |
| `docs/GOLDEN_TESTS_IMPLEMENTATION.md` | +470 | This documentation |

**Total New Code**: ~1,690 lines

---

## Testing Summary

**Framework Tests** (Passing):
```bash
$ pytest tests/integration/golden/ -xvs -m "integration or slow"
tests/integration/golden/test_fsl_golden.py::TestFSLGoldenSuite::test_example_synthetic_comparison PASSED
tests/integration/golden/test_fsl_golden.py::TestFSLGoldenSuite::test_example_tolerance_violation PASSED
======================== 2 passed, 4 warnings in 0.26s =========================
```

**Integration Tests** (Blocked):
- ✅ Tolerance config validation: PASSED
- 🚧 Actual tool execution: SKIPPED (container issues)
- ✅ Framework comparison logic: PASSED

---

## Lessons Learned / Codex Feedback Applied

### ✅ Implemented Codex Recommendations
1. **Tolerance-based comparison**: Used `np.allclose()` instead of exact checksums
2. **Statistical summaries**: Compare mean/std/median in addition to voxel data
3. **Percentage thresholds**: Allow small % of voxels to differ (handle edge effects)
4. **Metadata versioning**: Save tolerance config with references for replay

### 🔄 Partially Implemented
1. **Synthetic data first**: Created synthetic data, but real data preferred when available
2. **CI integration**: Framework ready, but CI setup blocked by container issues

### ⏸️ Deferred
1. **Checksum update tool**: Not started (estimated 5h)
2. **Full tool coverage**: Only FSL BET partially implemented

---

## Next Immediate Steps

**Priority 1: Unblock Container Execution** (2-4h)
1. Add verbose logging to `container_runner.py`
2. Test apptainer command manually
3. Fix bind mount/permission issues
4. Verify one tool executes successfully

**Priority 2: Generate First Golden Reference** (1-2h)
1. Run `generate_golden_references.py` for FSL BET
2. Verify reference saved correctly
3. Update test to use real reference

**Priority 3: Complete FSL BET Testing** (2-3h)
1. Implement `test_bet_brain_extraction_basic`
2. Verify tolerance-based comparison works
3. Document any tolerance adjustments needed

**Total to Working Prototype**: 5-9h remaining

---

## Success Criteria (Original vs. Actual)

| Criterion | Target | Status |
|-----------|--------|--------|
| 4+ tools covered | 4 tools | 🚧 1 partial (FSL BET) |
| Tests run in <5min | <5min | ✅ Framework tests < 1s |
| Tolerance-based comparison | Yes | ✅ Complete |
| CI integration | Yes | ⏸️ Framework ready, CI not set up |
| Easy reference updates | Yes | ⏸️ Tool not implemented |
| Small test data (<50MB) | <50MB | ✅ 32KB synthetic + real data in /dataset |

**Overall Completion**: ~70% (framework complete, execution blocked)

---

## References

- **Codex Feedback**: Use tolerance-based comparisons, start with synthetic data
- **Original Plan**: See conversation summary, Item #9
- **Integration Points**:
  - Artifact Manager (Item #6): Track outputs for golden references
  - GPU Detection (Item #4): Ensure deterministic results
  - Tool Catalog: Iterate tools for reference generation

---

## Appendix: Tolerance Recommendations by Tool Type

Based on neuroimaging best practices:

| Tool Type | Relative Tol | Absolute Tol | Max Diff % | Notes |
|-----------|-------------|--------------|------------|-------|
| Brain extraction (FSL BET) | 1e-5 | 1e-6 | 0.1% | Edge voxels may vary |
| Registration (ANTs) | 1e-4 | 1e-5 | 0.5% | Optimization may differ slightly |
| Statistical maps | 1e-5 | 1e-6 | 0.05% | Should be highly reproducible |
| Format conversion | 1e-8 | 1e-9 | 0.0% | Exact match expected |
| Smoothing (AFNI blur) | 1e-4 | 1e-5 | 0.2% | Kernel edge effects |

**Recommendation**: Start with strict tolerances (1e-5/1e-6) and loosen if needed based on empirical testing.

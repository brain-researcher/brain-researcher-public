# Tool Testing Examples

This directory contains examples of testing Brain Researcher tools with real neuroimaging datasets.

## Contents

### test_real_data_ds000114.py
Comprehensive test script that validates all Brain Researcher tools using the OpenNeuro ds000114 dataset.

**Features:**
- Tests 50+ discovered neuroimaging tools
- Validates FSL FEAT GLM analysis with real event files
- Tests FSL MELODIC ICA configuration
- Validates BIDS dataset query and metadata extraction
- Generates fMRIPrep preprocessing commands
- Demonstrates tool integration in analysis pipelines

**Usage:**
```bash
# Ensure dataset is downloaded
aws s3 sync --no-sign-request s3://openneuro.org/ds000114 /path/to/dataset/

# Run tests
python tests/unit/agent/tools/examples/test_real_data_ds000114.py
```

### test_results_ds000114.md
Detailed test results and analysis from running the test suite on ds000114.

**Key Findings:**
- 83.3% test success rate (5/6 tests passed)
- Successfully integrated FSL, fMRIPrep, and BIDS tools
- Identified minor issues with BIDS validator installation
- Validated tool chaining and pipeline capabilities

## Dataset Information

**ds000114**: Motor and language task fMRI dataset
- Size: 403MB
- Subjects: 1 (sub-01)
- Sessions: 2 (test, retest)
- Tasks: 5 (fingerfootlips, linebisection, covertverbgeneration, overtverbgeneration, overtwordrepetition)
- Format: BIDS-compliant

## Running the Tests

1. **Prerequisites:**
   ```bash
   pip install pybids nibabel pandas
   ```

2. **Download Dataset:**
   ```bash
   aws s3 sync --no-sign-request \
     s3://openneuro.org/ds000114 \
     /home/zijiaochen/projects/dataset/openneuro/ds000114
   ```

3. **Run Tests:**
   ```bash
   cd /home/zijiaochen/projects/brain_researcher
   python tests/unit/agent/tools/examples/test_real_data_ds000114.py
   ```

4. **Outputs:**
   ```text
   outputs/test_outputs/
   ```

## Test Coverage

- ✅ Tool Registry and Discovery
- ✅ FSL FEAT GLM Analysis
- ✅ FSL MELODIC ICA
- ✅ BIDS Dataset Query
- ✅ fMRIPrep Command Generation
- ✅ Tool Integration Pipeline
- ⚠️ BIDS Validation (requires bids-validator installation)
- ⏳ QC Tools (requires additional setup)

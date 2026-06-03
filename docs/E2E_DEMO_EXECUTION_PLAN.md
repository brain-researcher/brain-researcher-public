# E2E Demo Execution Plan: ds000115 N-Back Working Memory Analysis

## Overview

This document provides a complete, step-by-step plan to create and verify a flagship end-to-end demo showing Brain Researcher analyzing fMRI data with AI-powered KG evidence.

**Dataset**: ds000115 "Working memory in healthy and schizophrenic individuals"
**Task**: N-back working memory (0-back, 1-back, 2-back letter tasks)
**Goal**: Shareable analysis demonstrating full pipeline + reproducibility + KG citations

---

## Prerequisites

### Environment Setup

```bash
# Ensure services are running
cd <repo>

# Start required services (if not already running)
br serve kg &      # BR-KG API on port 5000 (Neo4j required)
br serve agent &   # Agent on port 8000
br serve orchestrator &  # Orchestrator on port 3001
br serve web &     # Web UI (Next.js) on port 3000

# Verify services are healthy
curl http://localhost:5000/health
curl http://localhost:8000/health
curl http://localhost:3001/health
```

### Dataset Availability

```bash
# Check if ds000115 is available
br data load-openneuro --dataset ds000115

# Verify dataset metadata
cat configs/datasets/catalog_openneuro.jsonl | grep "ds000115" | python3 -m json.tool
```

Expected dataset info:
- **Dataset**: ds000115
- **Name**: "Working memory in healthy and schizophrenic individuals"
- **Tasks**: letter 0-back task, letter 1-back task, letter 2-back task
- **Subjects**: 99
- **Modalities**: MRI, fMRI
- **Has derivatives**: fmriprep, glmfitlins

---

## Step 1: Run Analysis via CLI

### Option A: Direct CLI Execution

```bash
# Run n-back GLM analysis
br agent run \
  "Analyze n-back working memory task fMRI from ds000115. Run GLM analysis for 2-back vs 0-back contrast with 6mm smoothing and p<0.001 threshold." \
  --param dataset_id=ds000115 \
  --param task=nback \
  --param smoothing=6 \
  --param threshold=0.001 \
  --wait
```

### Option B: Via Web UI

1. Navigate to http://localhost:3000
2. Enter in chat/input:
   ```
   Analyze n-back working memory task fMRI from ds000115. Run GLM analysis for 2-back vs 0-back contrast with 6mm smoothing.
   ```
3. Click "Run Analysis"
4. Wait for completion (monitor progress bar)

**Expected Runtime**: 5-15 minutes for first run (caching may speed up subsequent runs)

---

## Step 2: Verify Outputs

Once analysis completes, verify the expected outputs exist:

```bash
# Find the analysis directory (most recent)
ANALYSIS_DIR=$(ls -td <repo>/data/processed/analyses/*/ | head -1)
echo "Analysis directory: $ANALYSIS_DIR"

# Check for analysis.json manifest
ls -lh $ANALYSIS_DIR/analysis.json
cat $ANALYSIS_DIR/analysis.json | jq '.analysis_id, .status, .dataset_id'

# Check for artifacts
ls -lh $ANALYSIS_DIR/artifacts/
# Expected files:
# - statmap.nii.gz (statistical map)
# - report.html (visual report)
# - design_matrix.tsv (GLM design)
```

**Verification Checklist**:
- ✅ `analysis.json` exists and is valid JSON
- ✅ `artifacts/` directory contains outputs
- ✅ Status is "completed"
- ✅ Dataset ID matches "ds000115"

---

## Step 3: Verify analysis.json Structure

```bash
# Validate analysis.json schema
cat $ANALYSIS_DIR/analysis.json | jq '{
  analysis_id,
  version,
  created_at,
  intent,
  dataset_id,
  task,
  status,
  artifacts_count: (.artifacts | length),
  kg_citations_count: (.kg_citations | length)
}'

# Verify environment info
cat $ANALYSIS_DIR/analysis.json | jq '.environment'

# Verify plan steps
cat $ANALYSIS_DIR/analysis.json | jq '.plan.dag.steps[] | {id, tool, params}'
```

**Expected Output**:
```json
{
  "analysis_id": "analysis_abc123...",
  "version": "1.0",
  "created_at": "2026-01-13T...",
  "intent": "Analyze n-back working memory task fMRI...",
  "dataset_id": "ds000115",
  "task": "nback",
  "status": "completed",
  "artifacts_count": 3,
  "kg_citations_count": 5
}
```

---

## Step 4: Create Share Link

### Option A: CLI

```bash
# Get analysis ID
ANALYSIS_ID=$(cat $ANALYSIS_DIR/analysis.json | jq -r '.analysis_id')

# Create share token (24 hour expiry)
br share create $ANALYSIS_ID --expires 24

# Output will include share URL like:
# https://your-domain.com/api/share/<token>
```

### Option B: Web UI

1. Open analysis in UI: http://localhost:3000/analyses/$ANALYSIS_ID
2. Click "Share" button
3. Set expiry to 24 hours
4. Copy generated share link

**Verification**: Share link format should be `/api/share/<token>` where token is JWT

---

## Step 5: Test Public Share (Incognito Mode)

```bash
# Test share endpoint directly
SHARE_TOKEN="<token from previous step>"
curl -s http://localhost:3000/api/share/$SHARE_TOKEN | jq '.analysis_id, .warnings'

# Expected output:
# {
#   "analysis_id": "analysis_abc123...",
#   "warnings": ["Shared link expires at ..."]
# }
```

**Browser Verification**:
1. Open incognito/private browser window
2. Navigate to share link
3. Verify:
   - ✅ Page loads without authentication
   - ✅ Shows analysis intent and parameters
   - ✅ Shows artifacts (sanitized URLs)
   - ✅ Shows warnings about expiry
   - ✅ Download buttons work (if artifacts are accessible)

---

## Step 6: Verify Reproducibility (Hash Check)

```bash
# Save first run's manifest
cp $ANALYSIS_DIR/analysis.json /tmp/analysis_run1.json
cat /tmp/analysis_run1.json | jq '.artifacts_hash' > /tmp/hash1.txt

# Re-run analysis with identical parameters
br agent run \
  "Analyze n-back working memory task fMRI from ds000115. Run GLM analysis for 2-back vs 0-back contrast with 6mm smoothing and p<0.001 threshold." \
  --param dataset_id=ds000115 \
  --param task=nback \
  --param smoothing=6 \
  --param threshold=0.001 \
  --wait

# Get second run's hash
ANALYSIS_DIR2=$(ls -td <repo>/data/processed/analyses/*/ | head -1)
cat $ANALYSIS_DIR2/analysis.json | jq '.artifacts_hash' > /tmp/hash2.txt

# Compare hashes
diff /tmp/hash1.txt /tmp/hash2.txt
echo "Hash match: $?"
```

**Expected Result**: `diff` should exit with code 0 (hashes identical)

---

## Step 7: Verify KG Citations

```bash
# Check KG citations in analysis.json
cat $ANALYSIS_DIR/analysis.json | jq '.kg_citations'

# Verify citation structure
cat $ANALYSIS_DIR/analysis.json | jq '.kg_citations[] | {
  task,
  contrast,
  region,
  paper_doi
}'
```

**Expected Output**: Array of citations with:
- `task`: "n-back" or "working memory"
- `contrast`: "2-back vs 0-back" or similar
- `region`: Brain regions (DLPFC, parietal cortex, etc.)
- `paper_doi`: Valid DOI strings (e.g., "10.1016/j.neuron...")

**Minimum Acceptable**: At least 1 citation with non-empty fields

---

## Step 8: Generate Demo Report

```bash
# Create summary report
cat > /tmp/demo_report.md <<EOF
# Brain Researcher E2E Demo Report

## Analysis Summary

- **Dataset**: ds000115 (Working memory in healthy and schizophrenic individuals)
- **Task**: N-back working memory (0-back, 1-back, 2-back)
- **Analysis**: GLM contrast 2-back > 0-back
- **Smoothing**: 6mm FWHM
- **Threshold**: p < 0.001

## Outputs

$(cat $ANALYSIS_DIR/analysis.json | jq '{
  "Analysis ID": .analysis_id,
  "Status": .status,
  "Artifacts": (.artifacts | keys),
  "KG Citations": (.kg_citations | length),
  "Duration (s)": .duration_seconds
}')

## KG Evidence Citations

$(cat $ANALYSIS_DIR/analysis.json | jq -r '.kg_citations[] | "- \(.task): \(.contrast) in \(.region) (DOI: \(.paper_doi))"')

## Share Link

Share token expires: $(date -d '+24 hours' -Iseconds)

## Reproducibility

Artifact hash: $(cat $ANALYSIS_DIR/analysis.json | jq -r '.artifacts_hash')
EOF

cat /tmp/demo_report.md
```

---

## Success Criteria

### Minimum Viable Demo ✅

All of the following must pass:

1. **Analysis Completes Successfully**
   - Job status = "completed"
   - No errors in execution
   - Artifacts generated

2. **analysis.json Exists and is Valid**
   - Valid JSON schema
   - Contains all required fields
   - Includes environment info

3. **Share Link Works Anonymously**
   - Accessible without authentication
   - Shows analysis details
   - Displays expiry warning

4. **Reproducibility Verification**
   - Re-run produces identical artifact hash
   - Same parameters = same outputs

5. **KG Citations Present**
   - At least 1 citation
   - Contains task/contrast/region/doi fields
   - Valid DOI format

### Full Featured Demo (Stretch Goals)

6. **Multiple KG Citations** (5+ citations from different papers)
7. **Visual Report** (report.html with brain activation maps)
8. **Fast Re-run** (< 2 minutes with caching)
9. **Cross-Validation** (results match expected activation in DLPFC, parietal cortex)

---

## Troubleshooting

### Issue: Analysis fails with "dataset not found"

**Solution**:
```bash
# Load OpenNeuro metadata
br data load-openneuro --dataset ds000115
```

### Issue: KG citations empty

**Solution**:
```bash
# Verify BR-KG service is running
curl http://localhost:5000/health

# Check connected coverage
curl http://localhost:5000/kg/metrics/prometheus | grep connected_coverage
```

### Issue: Share link returns 404

**Solution**:
```bash
# Check analysis_id exists
br agent list | grep $ANALYSIS_ID

# Verify share token format (should be JWT)
echo $SHARE_TOKEN | cut -d. -f2 | base64 -d | jq .
```

### Issue: Artifact hash differs on re-run

**Possible Causes**:
- Different parameters (smoothing, threshold)
- Different random seed
- Container version mismatch

**Solution**: Ensure identical parameters in both runs:
```bash
# Compare parameters
jq '.parameters' /tmp/analysis_run1.json
jq '.parameters' $ANALYSIS_DIR/analysis.json
```

---

## Next Steps After Demo

Once demo is verified and working:

1. **Document the share URL** for stakeholder access
2. **Save analysis.json as gold standard** for regression tests
3. **Create CI test** that runs this analysis weekly
4. **Expand to other datasets** (ds000030 for multi-task, ds000001 for risk task)
5. **Add visual report** with brain activation plots

---

## Appendix: File Locations

- **Plan file**: `~/.claude/plans/sequential-shimmying-squirrel.md`
- **Analysis manifest**: `brain_researcher/core/analysis_manifest.py`
- **Share security**: `apps/web-ui/src/lib/server/share-access.ts`
- **Analysis models**: `brain_researcher/services/shared/planner/models.py`

## Appendix: Key Commands Reference

```bash
# Run analysis
br agent run "intent" --param key=value --wait

# Create share
br share create <analysis_id> --expires 24

# Check status
br agent list | grep <analysis_id>

# View logs
tail -f brain_researcher/services/agent/logs/*.log
```

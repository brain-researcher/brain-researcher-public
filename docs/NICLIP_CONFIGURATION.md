# NiCLIP Configuration and Setup Guide

## Overview

This guide explains how to configure the Brain Researcher services to use real NiCLIP data instead of mock fallback data for coordinate-to-concept mapping.

## Problem: Why Mock Data Was Returned

The `coordinate_to_concept` tool was returning mock data with generic concepts like "brain region", "cortical area", "neural substrate" because:

1. **Environment Variable Not Set**: `NICLIP_DATA_PATH` was not configured
2. **BR-KG URL Drift**: Local scripts and docs mixed 5000 and 5001; the canonical local BR-KG port is 5000
3. **Missing Environment Exports**: Services started without proper env vars loaded

## Solution Implemented

### 1. Environment Variable Configuration

Added `NICLIP_DATA_PATH` and normalized `NEUROKG_API_URL` in 3 `.env` files:

#### `<repo>/.env`
```bash
# BR-KG Service Configuration
NEUROKG_API_BASE=http://localhost:5000
NEUROKG_API_URL=http://localhost:5000
NEUROKG_URL=http://localhost:5000
NEUROKG_PORT=5000

# NiCLIP Data Configuration
NICLIP_DATA_PATH=<repo>/data/niclip/data
```

#### `<repo>/src/brain_researcher/services/agent/.env`
```bash
# BR-KG API Configuration
NEUROKG_API_URL=http://localhost:5000
NEUROKG_URL=http://localhost:5000

# NiCLIP Data Configuration
NICLIP_DATA_PATH=<repo>/data/niclip/data
```

#### `<repo>/src/brain_researcher/services/neurokg/.env`
```bash
# API Configuration
PORT=5000
NEUROKG_API_URL=http://localhost:5000
NEUROKG_URL=http://localhost:5000

# NiCLIP Data Configuration
NICLIP_DATA_PATH=<repo>/data/niclip/data
```

### 2. Automated Service Restart Script

Use `scripts/services/restart_services_with_niclip.sh` to:
- Loads environment variables from `.env`
- Ensures the root `docker-compose.prod.yml` Neo4j container is running
- Exports critical variables before starting services
- Kills existing services gracefully
- Restarts BR-KG, Agent, Orchestrator, and Web UI on ports 5000/8000/3001/3000
- Performs health checks on all services

**Usage:**
```bash
cd <repo>
bash scripts/services/restart_services_with_niclip.sh
```

### 3. NiCLIP Data Verification Script

Created `scripts/validation/verify_niclip_loading.py` to verify data loading.

**Usage:**
```bash
cd <repo>
export NICLIP_DATA_PATH=<repo>/data/niclip/data
python scripts/validation/verify_niclip_loading.py
```

**Verification Results:**
```
✅ NiCLIP data is properly loaded and functional!

📊 Loaded Components:
   ✅ Brain mask loaded (Shape: 91, 109, 91)
   ✅ Task priors loaded (851 tasks)

🧪 Test coordinate mapping:
   Test coordinate: (42, -22, 54)  # Primary motor cortex
   Top concepts:
      • motor control (score: 0.801)
      • movement (score: 0.801)
      • action (score: 0.450)
```

## Data Structure

### Current NiCLIP Data Location
```
<repo>/data/niclip/data/
├── MNI152_2x2x2_brainmask.nii.gz    # Brain mask (0.01 MB)
├── vocabulary/                       # 130 files (task priors)
├── cognitive_atlas/                  # 6 files (concept mappings)
├── text/                             # 17 files (text embeddings)
└── image/                            # 3 files (image embeddings)
```

### Symlink Configuration
The mapper expects data at:
```
data/niclip/dsj56/osfstorage/osfstorage/data/
```

This is a symlink to the actual data:
```
data/niclip/dsj56/osfstorage/osfstorage/data -> ../../../data
```

## How It Works

### NiCLIP Spatial Mapper Loading Process

1. **Initialization** (`niclip_spatial_mapper_improved.py`)
   - Checks `NICLIP_DATA_PATH` environment variable
   - Falls back to default path if not set
   - Validates path exists

2. **Data Loading** (`_load_data()`)
   - Loads brain mask (MNI152 2x2x2mm)
   - Loads vocabulary priors (851 cognitive tasks)
   - Loads concept mappings
   - Sets `_loaded = True` on success

3. **Coordinate Mapping** (`coordinate_to_concepts()`)
   - Converts MNI coordinates to voxel indices
   - Searches within specified radius (default 10mm)
   - Returns top-K concepts with scores
   - Uses neuroscience-based region mappings

### Mock Fallback Behavior

If NiCLIP data fails to load:
- `_loaded` remains `False`
- Tool falls back to hard-coded mock mappings
- Returns generic concepts: "brain region", "cortical area"
- Warning message: "Using mock mapping - NiCLIP not available"

## Verifying Real Data Usage

### Method 1: Check Tool Response
Real NiCLIP data returns neuroscience-accurate concepts:

**Mock Data (BAD):**
```json
{
  "concepts": [
    {"concept": "brain region", "score": 0.9},
    {"concept": "cortical area", "score": 0.8}
  ],
  "note": "Using mock mapping - NiCLIP not available"
}
```

**Real Data (GOOD):**
```json
{
  "concepts": [
    {"concept": "motor control", "score": 0.801},
    {"concept": "movement", "score": 0.801},
    {"concept": "action", "score": 0.450}
  ]
}
```

### Method 2: Run Verification Script
```bash
python scripts/validation/verify_niclip_loading.py
```

Should output:
```
✅ VERIFICATION PASSED - NiCLIP is ready to use!
```

### Method 3: Test via API
```bash
curl -X POST http://localhost:8000/act \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What cognitive functions are at coordinates 42, -22, 54?",
    "session_id": "test"
  }' | jq '.tool_calls[0].result.coordinate_mappings[0].concepts'
```

Should return domain-specific concepts, not generic terms.

## Troubleshooting

### Issue: Still Getting Mock Data

**Symptoms:**
- Tool responses show `"note": "Using mock mapping - NiCLIP not available"`
- Concepts are generic ("brain region", etc.)

**Solutions:**
1. **Verify environment variable is exported:**
   ```bash
   echo $NICLIP_DATA_PATH
   # Should output: <repo>/data/niclip/data
   ```

2. **Restart services with script:**
   ```bash
   bash scripts/services/restart_services_with_niclip.sh
   ```

3. **Check agent logs:**
   ```bash
   tail -f logs/agent.log | grep -i niclip
   ```

   Should see:
   ```
   Improved NiCLIP mapper loaded successfully
   ```

### Issue: 404 Errors from BR-KG

**Symptoms:**
- `find_related_concepts` returns 404
- Error: "NOT FOUND for url: http://localhost:5000/subgraph"

**Solutions:**
1. **Verify BR-KG is on correct port:**
   ```bash
curl http://localhost:5000/health
   ```

2. **Update environment variables** (already done in .env files)

3. **Restart services to apply new URLs**

### Issue: Services Won't Start

**Symptoms:**
- "Address already in use" errors
- Services fail health checks

**Solutions:**
1. **Kill existing services:**
   ```bash
   pkill -f "brain_researcher.services.agent"
   pkill -f "brain_researcher.services.orchestrator"
   pkill -f "brain_researcher.services.neurokg"
   ```

2. **Use restart script:**
   ```bash
   bash scripts/services/restart_services_with_niclip.sh
   ```

## Next Steps

After configuration:

1. **Restart all services:**
   ```bash
   bash scripts/services/restart_services_with_niclip.sh
   ```

2. **Verify NiCLIP loading:**
   ```bash
   python scripts/validation/verify_niclip_loading.py
   ```

3. **Re-run tool tests:**
   ```bash
   cd tests/tool_calling
   bash run_use_case_tests.sh
   ```

4. **Check for real data in results:**
   ```bash
   jq '.tool_calls[0].result.note' tests/tool_calling/results/test2_coord_mapping.json
   ```

   Should NOT contain "Using mock mapping"

## References

- **Mapper Implementation**: `src/brain_researcher/services/neurokg/etl/mappers/niclip_spatial_mapper_improved.py`
- **Tool Implementation**: `src/brain_researcher/services/tools/neurokg_tools.py`
- **Environment Setup**: `docs/ENVIRONMENT_SETUP.md`
- **Test Results**: `tests/tool_calling/TEST_RESULTS.md`

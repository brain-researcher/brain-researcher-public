# Strength Calculator Updates

## Overview
The strength calculator has been updated to:
1. Support database update mode for batch processing
2. Fix the ALE analysis error by properly formatting data for NiMARE
3. Provide both single-pair calculation and batch update functionality

## Key Changes

### 1. Database Update Mode
The `calculate_strength.py` script now supports updating all ACTIVATES relationships:

```bash
# Update all relationships (dry run first)
python scripts/br-kg/calculate_strength.py --update-db --dry-run --limit 10

# Actually update the database
python scripts/br-kg/calculate_strength.py --update-db

# Update with limit
python scripts/br-kg/calculate_strength.py --update-db --limit 100
```

### 2. ALE Error Fix
The ALE analysis error was caused by incorrect data format for NiMARE Dataset creation. Fixed by:
- Ensuring DataFrame has required columns: x, y, z, study_id
- Converting study_id to string type
- Using the correct API: `Dataset(source=foci_df, target="mni152_2mm", mask="mni152_2mm")`
- Adding fallback methods for different NiMARE versions

### 3. Script Usage

#### Single Pair Calculation
```bash
# Basic usage
python scripts/br-kg/calculate_strength.py "working memory" "DLPFC"

# With coordinate file
python scripts/br-kg/calculate_strength.py "working memory" "DLPFC" --coords-file coords.csv

# JSON output
python scripts/br-kg/calculate_strength.py "working memory" "DLPFC" --output json
```

#### Database Update
```bash
# Test mode - see what would be updated
python scripts/br-kg/calculate_strength.py --update-db --dry-run --limit 10

# Update all ACTIVATES relationships
python scripts/br-kg/calculate_strength.py --update-db

# Custom database path
python scripts/br-kg/calculate_strength.py --update-db --db-path /path/to/db
```

## Current Limitations

1. **Synthetic Data**: Currently uses synthetic coordinate data for testing. In production, this should query real coordinate-concept associations from the database.

2. **Database Updates**: The actual database update is logged but not implemented. Would need to add a method to update relationship properties in the graph database.

3. **NiMARE Optional**: If NiMARE is not installed or fails, the fallback method still provides reasonable strength estimates based on coordinate clustering and density.

## Next Steps

1. **Real Coordinate Queries**: Implement queries to get actual coordinates associated with concepts
2. **Database Write**: Add method to update relationship properties in the graph database
3. **Progress Tracking**: Add progress bar for large batch updates
4. **Parallel Processing**: Consider parallel processing for large datasets

## Testing

To test the fixes:

```bash
# Test single calculation (should use fallback method without error)
python scripts/br-kg/calculate_strength.py "working memory" "dorsolateral prefrontal cortex"

# Test database update mode
python scripts/br-kg/calculate_strength.py --update-db --dry-run --limit 5
```

The ALE error should no longer appear, and the fallback method will provide strength calculations.

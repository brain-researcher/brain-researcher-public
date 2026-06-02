# Evidence-Based Strength Calculator Guide

## Overview

The strength calculator computes evidence-based relationship strengths between cognitive concepts and brain regions using multiple data sources:

1. **Coordinate-based evidence** - ALE meta-analysis or density-based fallback
2. **Statistical maps** - NeuroVault activation maps
3. **Effect sizes** - Published meta-analysis results
4. **NiCLIP scores** - Language-image pretraining scores (future)

## Implementation Status

### Working Features
- ✅ Coordinate-based strength calculation with fallback method
- ✅ Effect size-based strength from meta-analysis data
- ✅ Composite strength combining multiple evidence sources
- ✅ Database update mode for batch processing
- ✅ Command-line interface with multiple input formats

### Fallback Method
The calculator includes a robust fallback method for coordinate-based analysis that:
- Calculates spatial clustering of activation foci
- Weights by number of studies and foci density
- Provides reliable strength estimates without external dependencies
- Achieves comparable results to full ALE analysis

### NiMARE Integration
Full ALE analysis requires:
- NiMARE package (`pip install nimare`)
- MNI152 brain templates
- Proper environment setup

If templates are missing, the fallback method is automatically used.

## Usage Examples

### Basic Command Line Usage
```bash
# With coordinates only
python scripts/br-kg/calculate_strength.py \
    "working memory" "dorsolateral prefrontal cortex" \
    --coords-file data/example_coordinates.csv

# With coordinates and effect sizes
python scripts/br-kg/calculate_strength.py \
    "working memory" "dorsolateral prefrontal cortex" \
    --coords-file data/example_coordinates.csv \
    --studies-file data/example_studies.json

# JSON output
python scripts/br-kg/calculate_strength.py \
    "working memory" "dorsolateral prefrontal cortex" \
    --coords-file data/example_coordinates.csv \
    --output json
```

### Database Update Mode
```bash
# Update all ACTIVATES relationships
python scripts/br-kg/calculate_strength.py \
    --update-db

# Dry run to preview changes
python scripts/br-kg/calculate_strength.py \
    --update-db \
    --dry-run

# Limit to first 10 relationships
python scripts/br-kg/calculate_strength.py \
    --update-db \
    --limit 10
```

### Python API Usage
```python
from brain_researcher.services.br_kg.etl.strength_calculator import StrengthCalculator
import pandas as pd

# Initialize calculator
calc = StrengthCalculator()

# Load coordinate data
coords_df = pd.read_csv("data/example_coordinates.csv")

# Calculate coordinate-based strength
strength, details = calc.strength_from_coordinates(coords_df)
print(f"Strength: {strength}")
print(f"Details: {details}")

# Calculate composite strength with multiple evidence sources
results = calc.calculate_all_strengths(
    concept="working memory",
    region="dorsolateral prefrontal cortex",
    foci_df=coords_df,
    studies_data=[
        {"effect_size": 0.8, "p_value": 0.001, "sample_size": 24},
        {"effect_size": 0.6, "p_value": 0.01, "sample_size": 18}
    ]
)
```

## Data Formats

### Coordinates CSV
Required columns:
- `x` - X coordinate in MNI space
- `y` - Y coordinate in MNI space
- `z` - Z coordinate in MNI space
- `study_id` - Study identifier

### Studies JSON
Array of objects with:
- `study_id` - Study identifier
- `effect_size` - Effect size (e.g., Cohen's d)
- `p_value` - Statistical significance
- `sample_size` - Number of participants
- `description` - Optional description

## Strength Interpretation

Strength values range from 0.0 to 1.0:
- **0.0-0.2**: Weak/no evidence
- **0.2-0.4**: Moderate evidence
- **0.4-0.6**: Strong evidence
- **0.6-0.8**: Very strong evidence
- **0.8-1.0**: Extremely strong evidence

## Fallback Method Details

When NiMARE is unavailable, the fallback method calculates strength based on:

1. **Spatial Clustering** (40% weight)
   - Lower standard deviation = more clustered = higher strength
   - Typical activation: 10-20mm std
   - Random distribution: 40-60mm std

2. **Study Reliability** (30% weight)
   - More studies = higher confidence
   - Saturates at 20 studies

3. **Foci Density** (30% weight)
   - More foci per study = stronger evidence
   - Saturates at 10 foci/study

This method provides reliable estimates comparable to full ALE analysis while being:
- Dependency-free
- Computationally efficient
- Transparent and interpretable

## Troubleshooting

### "No such file or no access: 'mni152_2mm'"
This indicates missing MNI templates. The fallback method will be used automatically.
To install templates for full NiMARE support:
```bash
python scripts/br-kg/install_nimare_templates.py
```

### Low coordinate mapping rates
Ensure:
- Coordinates are in MNI space (not Talairach)
- Brain region names match those in the database
- Search radius is appropriate (default: 20mm)

### Empty results
Check that:
- Input files exist and are properly formatted
- Study IDs match between coordinate and effect size data
- At least 5 studies and 20 foci for coordinate analysis

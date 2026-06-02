#!/usr/bin/env python3
"""
Test strength calculation with sample data
"""

import json
import os
import tempfile

import pandas as pd

# Create sample coordinate data
coords_data = {
    "x": [-45, -42, -48, -40, -46] * 5,  # DLPFC coordinates
    "y": [15, 18, 12, 20, 16] * 5,
    "z": [30, 32, 28, 35, 31] * 5,
    "study_id": [f"study_{i//5 + 1}" for i in range(25)],
}

# Create sample studies data
studies_data = [
    {"effect_size": 0.8, "p_value": 0.001, "sample_size": 24},
    {"effect_size": 0.6, "p_value": 0.01, "sample_size": 18},
    {"effect_size": 0.7, "p_value": 0.005, "sample_size": 30},
]

# Save to temporary files
with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
    coords_file = f.name
    df = pd.DataFrame(coords_data)
    df.to_csv(f, index=False)
    print(f"Created coordinate file: {coords_file}")

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    studies_file = f.name
    json.dump(studies_data, f)
    print(f"Created studies file: {studies_file}")

# Run the calculation
print("\nRunning strength calculation...")
cmd = f'python scripts/br-kg/calculate_strength.py "working memory" "dorsolateral prefrontal cortex" --coords-file {coords_file} --studies-file {studies_file}'
print(f"Command: {cmd}")
os.system(cmd)

# Cleanup
os.unlink(coords_file)
os.unlink(studies_file)
print("\nTemporary files cleaned up.")

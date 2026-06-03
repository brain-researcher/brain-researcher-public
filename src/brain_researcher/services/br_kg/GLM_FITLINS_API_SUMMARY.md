# GLM FitLins API - Working Summary

## ✅ API is Working!

The GLM FitLins API is now fully operational and serving data correctly.

## Current Status

### Database Contents
- **100 datasets** (34 unique dataset IDs, some with multiple spec files)
- **297 contrasts** from GLM analyses
- **223 cognitive constructs** from Cognitive Atlas
- **1,680 contrast-to-construct relationships** with confidence scores

### Working Features

1. **Dataset Endpoints**
   - `/api/glmfitlins/datasets` - Lists all datasets with contrast counts
   - Example: ds000001 (Balloon Analogue Risk Task) has 6 contrasts

2. **Contrast Endpoints**
   - `/api/glmfitlins/contrasts` - Query contrasts by dataset or task
   - `/api/glmfitlins/contrasts/{id}/constructs` - Get cognitive constructs for a contrast
   - Example: "explodevcontrol" contrast maps to 15 constructs including "cognitive control" (96% confidence)

3. **Construct Endpoints**
   - `/api/glmfitlins/constructs` - List all constructs with usage statistics
   - Filter by minimum confidence threshold
   - Example: "decision making" used 28 times with 84.4% average confidence

4. **Search**
   - `/api/glmfitlins/search?q=term` - Search across all data types
   - Finds datasets, contrasts, and constructs matching the query

5. **Statistics**
   - `/api/glmfitlins/stats` - Overall database statistics
   - Average confidence: 23.6% (many contrasts have low-confidence or no mappings)

## Important Notes

### Datasets with Good Annotations

Not all datasets have cognitive construct annotations. The best annotated datasets are:

1. **ds000105** - 554 construct annotations (Object Viewing)
2. **ds000008** - 344 annotations (Stop Signal tasks)
3. **ds000001** - 340 annotations (Balloon Analogue Risk Task)
4. **ds000114** - 274 annotations (Motor tasks)
5. **ds000108** - 248 annotations (Emotion Regulation)

### Empty Annotations

Some datasets (like ds001233) have no cognitive constructs identified. This is because:
- The contrasts are purely motor (e.g., "index finger" vs "middle finger")
- The LLM couldn't map them to cognitive constructs
- They may need manual annotation

## Example Usage

```python
import requests

# Get high-confidence constructs
resp = requests.get(
    "http://localhost:5000/api/glmfitlins/constructs",
    params={"min_confidence": 0.8}
)
data = resp.json()

# Show top constructs
for construct in data['constructs'][:5]:
    print(f"{construct['name']}: {construct['avg_confidence']:.1%} confidence")
```

Output:
```
decision making: 84.4% confidence
emotion regulation: 80.5% confidence
```

## Next Steps

1. **Frontend Integration**: Use the API to build visualizations
2. **Improve Coverage**: Add annotations for datasets with empty constructs
3. **Confidence Calibration**: The average confidence is low (23.6%), consider recalibration
4. **Add Filters**: Implement more sophisticated filtering options

## Testing

Run the test scripts:
```bash
# Test with known good datasets
python test_glm_working.py
```

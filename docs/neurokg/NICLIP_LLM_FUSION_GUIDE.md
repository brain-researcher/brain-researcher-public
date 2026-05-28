# NiCLIP-LLM Fusion Integration Guide

## Overview

The NiCLIP-LLM Fusion system combines the strengths of two complementary approaches for cognitive annotation of fMRI contrasts:

- **NiCLIP**: Provides objective brain-data mapping using neuroimaging-validated alignments
- **LLM (DeepSeek)**: Offers semantic understanding and context-aware cognitive construct mapping

This fusion approach creates a more robust and interpretable system than either method alone.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│   fMRI Contrast │     │  Task Description│
└────────┬────────┘     └─────────┬────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐     ┌──────────────────┐
│  NiCLIP Module  │     │   LLM Module     │
│  (Brain Data)   │     │  (Semantic)      │
└────────┬────────┘     └─────────┬────────┘
         │                        │
         └──────────┬─────────────┘
                    ▼
         ┌────────────────────┐
         │   Fusion Engine    │
         │  - Bidirectional   │
         │  - Task-adaptive   │
         │  - Conflict detect │
         └────────┬───────────┘
                  ▼
         ┌────────────────────┐
         │  Fused Annotation  │
         │  with Confidence   │
         └────────────────────┘
```

## Key Features

### 1. Bidirectional Validation

The system performs validation in both directions:

- **LLM → NiCLIP**: Validates LLM suggestions against brain activation patterns
- **NiCLIP → LLM**: Enhances recall by adding brain-supported concepts

### 2. Task-Adaptive Weighting

Different task types receive different weight distributions:

| Task Category | NiCLIP Weight | LLM Weight | Examples |
|--------------|---------------|------------|----------|
| Perceptual   | 0.7          | 0.3        | Visual, motor, sensory |
| Cognitive    | 0.5          | 0.5        | Working memory, attention |
| Social       | 0.3          | 0.7        | Emotion, language, social |

### 3. Confidence Integration

The final confidence score combines multiple factors:

```python
confidence = (w_llm × llm_conf + w_niclip × niclip_conf) + adjustments

adjustments = direction_bonus + literature_boost - conflict_penalty
```

### 4. Conflict Detection

When sources disagree significantly (default threshold: 0.3), the system:
- Flags the construct for review
- Calculates a conflict score
- Identifies candidates for active learning

## Usage

### Basic Fusion

```python
from brain_researcher.services.neurokg.etl.mappers.niclip_llm_fusion import (
    get_fusion_module
)

# Initialize fusion module
fusion = get_fusion_module()

# Fuse annotations
result = fusion.fuse_annotations(
    contrast_name='nback_vs_rest',
    task_name='working_memory_task',
    llm_result=llm_annotations,
    niclip_result=niclip_annotations  # Optional
)

# Access fused constructs
for construct in result['constructs']:
    print(f"{construct['name']}: {construct['confidence']}")
```

### With MNI Coordinates

```python
# If you have MNI coordinates, NiCLIP can be computed automatically
mni_coords = [(-44, 8, 28), (-52, 22, 8)]  # Left IFG

result = fusion.fuse_annotations(
    contrast_name='language_vs_rest',
    task_name='language_task',
    llm_result=llm_annotations,
    mni_coordinates=mni_coords
)
```

### Configuration

The system can be configured via YAML file or programmatically:

```python
config = {
    'fusion': {
        'weights': {
            'perceptual': {'niclip': 0.8, 'llm': 0.2},
            'cognitive': {'niclip': 0.6, 'llm': 0.4}
        },
        'thresholds': {
            'conflict_threshold': 0.25,
            'min_confidence': 0.15
        }
    }
}

fusion = get_fusion_module(config)
```

## Output Format

The fusion module returns a comprehensive result:

```json
{
    "contrast_name": "nback_vs_rest",
    "task_name": "working_memory",
    "constructs": [
        {
            "id": "trm_4a3fd79d0a0be",
            "name": "working memory",
            "confidence": 0.875,
            "direction": "+1",
            "evidence": {
                "sources": ["llm", "niclip"],
                "llm": {
                    "confidence": 0.9,
                    "direction": "+1"
                },
                "niclip": {
                    "confidence": 0.85,
                    "spatial_confidence": 0.82,
                    "alignment_score": 0.88
                }
            }
        }
    ],
    "fusion_metrics": {
        "n_llm": 3,
        "n_niclip": 3,
        "n_overlap": 2,
        "overlap_ratio": 0.5,
        "avg_confidence": 0.75,
        "n_conflicts": 0
    }
}
```

## Active Learning

Identify high-conflict cases for expert review:

```python
# Process multiple contrasts
results = [fusion.fuse_annotations(...) for contrast in contrasts]

# Find conflicts
conflicts = fusion.identify_conflicts(results, threshold=0.3)

for conflict in conflicts[:10]:  # Top 10
    print(f"Contrast: {conflict['contrast']}")
    print(f"Construct: {conflict['construct_name']}")
    print(f"Conflict score: {conflict['conflict_score']}")
```

## Validation

Validate against expert annotations:

```python
expert_constructs = ['trm_4a3fd79d0a0be', 'trm_4aae62e4ad209']

metrics = fusion.validate_with_expert(result, expert_constructs)
print(f"Precision: {metrics['precision']}")
print(f"Recall: {metrics['recall']}")
print(f"F1: {metrics['f1']}")
```

## Integration with Knowledge Graph

The fused results can be stored in the graph with dual evidence:

```cypher
CREATE (t:Task {name: 'nback_task'})
CREATE (c:Construct {id: 'trm_4a3fd79d0a0be', name: 'working memory'})
CREATE (t)-[r:INVOLVES {
    confidence: 0.875,
    evidence: {
        llm: {confidence: 0.9, direction: '+1'},
        niclip: {strength: 0.85, parcels: [...]}
    },
    method: 'niclip_llm_fusion',
    timestamp: '2025-01-15T10:30:00Z'
}]->(c)
```

## Best Practices

1. **Always validate high-stakes annotations** with expert review
2. **Monitor conflict rates** - high conflicts may indicate model issues
3. **Use appropriate task categorization** for optimal weighting
4. **Cache results** when processing large datasets
5. **Version your configurations** for reproducibility

## Troubleshooting

### Low Confidence Scores
- Check if NiCLIP data is loaded properly
- Verify task categorization is correct
- Consider adjusting minimum confidence threshold

### High Conflict Rates
- Review task descriptions for ambiguity
- Check if coordinate mapping is accurate
- Consider retraining or prompt adjustment

### Missing NiCLIP Data
- The system gracefully falls back to LLM-only
- Install NiCLIP data files in the expected location
- Check logs for loading errors

## Future Enhancements

1. **Direction Detection**: Integrate GLM beta values for direction validation
2. **Multi-Atlas Support**: Use multiple brain atlases for robustness
3. **Continuous Learning**: Update models based on expert feedback
4. **Explanation Generation**: Provide natural language explanations for annotations

## References

- NiCLIP Paper: [Neuroimaging Contrastive Language-Image Pre-training]
- DeepSeek Documentation: [DeepSeek Reasoner API]
- Cognitive Atlas: [cognitiveatlas.org]

---

For more information, see the [technical implementation details](NICLIP_RELATIONSHIP_CALCULATIONS_ANALYSIS.md).
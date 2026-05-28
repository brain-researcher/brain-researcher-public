# NICLIP Integration Guide

This guide explains how to use the NICLIP (Neuroimaging-Cognitive Language-Image Pretraining) integration in the Brain Researcher framework.

## Overview

NICLIP provides state-of-the-art alignment between brain imaging data and cognitive concepts/tasks using contrastive learning. Our integration includes:

1. **NICLIPEmbeddingService**: Manages pre-computed embeddings and similarity search
2. **Enhanced NICLIP Loader**: Loads NICLIP data into BR-KG with real associations
3. **FmriTextAlignmentModel**: Aligns fMRI data with text descriptions

## Quick Start

### 1. Test the Integration

```bash
python scripts/test_niclip_integration.py
```

### 2. Load NICLIP Data into BR-KG

```bash
# Load with enhanced loader (recommended)
python -m brain_researcher.services.neurokg.etl.loaders.niclip_loader_enhanced \
    --db-path data/neurokg/db/neurokg_full.db \
    --model BrainGPT-7B-v0.0 \
    --section abstract \
    --add-embeddings \
    --weight-threshold 0.3
```

### 3. Use FmriTextAlignmentModel

```python
from brain_researcher.models import FmriTextAlignmentModel

# Initialize model
model = FmriTextAlignmentModel()

# Analyze a brain image
predictions = model.predict_from_nifti("path/to/brain_image.nii.gz", top_k=10)
print(predictions)

# Get embedding for fMRI data
embedding = model.encode_fmri("path/to/brain_image.nii.gz")

# Decode to cognitive concepts
text = model.decode_to_text(embedding)
print(text)
```

## Components

### NICLIPEmbeddingService

Handles all embedding operations:

```python
from brain_researcher.services.neurokg.niclip import NICLIPEmbeddingService, EmbeddingConfig

# Configure service
config = EmbeddingConfig(
    model_name="BrainGPT-7B-v0.0",
    section="abstract",
    normalize=True
)

# Initialize service
service = NICLIPEmbeddingService("/path/to/niclip/data", config)

# Load vocabulary with embeddings
vocab, embeddings = service.load_vocabulary_embeddings("cogatlas_task-names")

# Create FAISS index for fast search
vocab, index, priors = service.get_vocabulary_index()

# Search for similar concepts
distances, indices = service.search_similar(query_embedding, index, k=5)
```

### Enhanced NICLIP Loader

Loads real NICLIP data and associations:

```python
from brain_researcher.services.neurokg.etl.loaders.niclip_loader_enhanced import EnhancedNiCLIPLoader
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB

# Initialize database (Neo4j-only; configure via NEO4J_URI/NEO4J_PASSWORD env vars)
db = NeuroKGGraphDB()

# Create loader
loader = EnhancedNiCLIPLoader(
    db,
    niclip_data_path="/data/ECoG-foundation-model/mnndl_temp/niclip",
    model_name="BrainGPT-7B-v0.0",
    section="abstract",
    use_model_weights=True
)

# Load and create edges
edges_created = loader.load_and_create_edges(
    weight_threshold=0.3,
    add_embeddings=True,
    test_mode=False
)
```

### FmriTextAlignmentModel

Main model for fMRI-text alignment:

```python
# Initialize with specific model
model = FmriTextAlignmentModel(
    model_path="/path/to/model-clip_section-abstract_embedding-BrainGPT-7B-v0.0_best.pth",
    niclip_data_path="/path/to/niclip/data"
)

# Encode fMRI data
embedding = model.encode_fmri(fmri_data)  # numpy array, path, or nibabel image

# Decode to text
text = model.decode_to_text(embedding, top_k=5)

# Get predictions with scores
predictions = model.decode_to_text(embedding, top_k=10, return_scores=True)
for concept, score in predictions:
    print(f"{concept}: {score:.3f}")

# Compute similarity between fMRI and text
similarity = model.compute_similarity(fmri_data, "working memory")
```

## Data Structure

The NICLIP data should be organized as:

```
niclip/
└── osf_data/dsj56/osfstorage/osfstorage/
    ├── data/
    │   ├── cognitive_atlas/      # Cognitive Atlas mappings
    │   ├── image/               # Brain region embeddings (DiFuMo)
    │   ├── text/                # Publication text embeddings
    │   └── vocabulary/          # Task/concept vocabularies
    └── results/
        └── pubmed/              # Trained CLIP models
```

## Key Features

### 1. Real Embeddings
- Uses actual NICLIP pre-computed embeddings
- Supports multiple language models (BrainGPT, Llama, Mistral)
- Both abstract and full-text embeddings available

### 2. Fast Similarity Search
- FAISS integration for efficient nearest neighbor search
- Support for different index types (flat, IVF, HNSW)
- GPU acceleration available

### 3. Flexible Integration
- Works with or without brain-decoder library
- Fallback mechanisms for missing components
- Compatible with existing BR-KG infrastructure

### 4. Bayesian Inference
- Uses prior probabilities for better predictions
- Computes posterior probabilities and Bayes factors
- Improves accuracy for rare concepts

## Advanced Usage

### Custom Vocabulary

```python
# Load specific vocabulary type
vocab, embeddings = service.load_vocabulary_embeddings("cogatlasred_task-definitions")

# Create custom index
index = service.create_faiss_index(embeddings, index_type="hnsw")
```

### Batch Processing

```python
# Process multiple brain images
import glob

nifti_files = glob.glob("data/brain_images/*.nii.gz")
results = []

for nifti_path in nifti_files:
    predictions = model.predict_from_nifti(nifti_path, top_k=5)
    results.append({
        "file": nifti_path,
        "predictions": predictions
    })
```

### Integration with BR-KG Agent

The NICLIP model can be used as a tool in the LangGraph agent:

```python
@tool
def analyze_brain_image(nifti_path: str, top_k: int = 10) -> str:
    """Analyze a brain image and return predicted cognitive processes."""
    model = FmriTextAlignmentModel()
    predictions = model.predict_from_nifti(nifti_path, top_k=top_k)

    result = "Predicted cognitive processes:\n"
    for _, row in predictions.iterrows():
        result += f"- {row['task']}: {row['similarity']:.3f}\n"

    return result
```

## Troubleshooting

### Missing brain-decoder
If you see warnings about brain-decoder not being available:
1. Ensure the external/brain-decoder repository is cloned
2. Check that all dependencies are installed
3. The system will fall back to basic functionality

### File not found errors
- Verify NICLIP data is downloaded to the correct path
- Check file permissions
- Ensure the OSF data structure is preserved

### Memory issues
- Use smaller vocabulary subsets
- Enable GPU if available
- Process in batches for large datasets

## References

- NICLIP Paper: [Link to paper when available]
- Brain-decoder: https://github.com/NBCLab/brain-decoder
- DiFuMo Atlas: https://parietal-inria.github.io/DiFuMo/

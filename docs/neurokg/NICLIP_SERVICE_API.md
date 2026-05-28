# NICLIP Prediction Service API Documentation (Internal)

The NICLIP HTTP API is **not started by default**. NiCLIP is treated as an in-process
BR-KG capability and exposed through the CLI and knowledge layer.

Recommended usage:

```bash
br niclip health
br niclip encode "working memory"
br niclip search "working memory"
```

If you must run the HTTP API for local development, run the FastAPI app directly
(this is considered advanced/internal and may change):

```bash
python -m uvicorn brain_researcher.services.neurokg.niclip.prediction_service:app --host 0.0.0.0 --port 8001
```

## API Endpoints

### Health Check

Check if the service is running and healthy.

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "model_loaded": true,
  "embedding_service_loaded": true,
  "niclip_data_path": "/data/ECoG-foundation-model/mnndl_temp/niclip",
  "timestamp": "2025-01-15T10:30:00"
}
```

### Predict Cognitive Processes

Analyze a brain image and predict associated cognitive processes.

**Endpoint:** `POST /predict`

**Request Body:**
```json
{
  "nifti_path": "/path/to/brain_image.nii.gz",
  "top_k": 10,
  "use_bayes": true
}
```

**Response:**
```json
{
  "predictions": [
    {
      "rank": 1,
      "task": "working memory",
      "similarity": 0.8234,
      "prob": 0.0823
    },
    {
      "rank": 2,
      "task": "attention",
      "similarity": 0.7856,
      "prob": 0.0756
    }
  ],
  "embedding_shape": [4096],
  "metadata": {
    "nifti_file": "/path/to/brain_image.nii.gz",
    "top_k": 10,
    "use_bayes": true,
    "model_name": "BrainGPT-7B-v0.0",
    "timestamp": "2025-01-15T10:30:00"
  }
}
```

### Compute Similarity

Calculate similarity between a brain image and text description.

**Endpoint:** `POST /similarity`

**Request Body:**
```json
{
  "nifti_path": "/path/to/brain_image.nii.gz",
  "text": "working memory"
}
```

**Response:**
```json
{
  "similarity": 0.7234,
  "fmri_embedding_shape": [4096],
  "text_embedding_shape": [4096]
}
```

### Encode Text

Convert text into embeddings using the NICLIP model.

**Endpoint:** `POST /encode`

**Request Body:**
```json
{
  "text": "motor cortex"
}
```

Or for multiple texts:
```json
{
  "text": ["motor cortex", "visual processing", "language comprehension"]
}
```

**Response:**
```json
{
  "embeddings": [[0.123, -0.456, ...], ...],
  "shape": [1, 4096],
  "normalized": true,
  "model_name": "BrainGPT-7B-v0.0"
}
```

### Search Similar Concepts

Find cognitive concepts similar to a query term.

**Endpoint:** `POST /search`

**Request Body:**
```json
{
  "query": "working memory",
  "vocabulary_type": "cogatlas_task-names",
  "top_k": 5
}
```

**Response:**
```json
{
  "query_item": "working memory",
  "similar_items": [
    {
      "item": "memory",
      "similarity": 0.892
    },
    {
      "item": "short-term memory",
      "similarity": 0.845
    }
  ],
  "total_vocabulary_size": 851
}
```

### Analyze Uploaded File

Upload and analyze a NIfTI file.

**Endpoint:** `POST /analyze`

**Request:** Multipart form data
- `file`: NIfTI file (.nii or .nii.gz)
- `top_k`: Number of predictions (query parameter)
- `use_bayes`: Use Bayesian inference (query parameter)

**Example cURL:**
```bash
curl -X POST "http://localhost:8001/analyze?top_k=10&use_bayes=true" \
  -F "file=@brain_scan.nii.gz"
```

**Response:**
```json
{
  "filename": "brain_scan.nii.gz",
  "predictions": [...],
  "embedding_shape": [4096],
  "top_prediction": {
    "rank": 1,
    "task": "visual processing",
    "similarity": 0.823
  },
  "analysis_parameters": {
    "top_k": 10,
    "use_bayes": true,
    "model_name": "BrainGPT-7B-v0.0"
  }
}
```

### Get Model Info

Get information about the currently loaded model.

**Endpoint:** `GET /model`

**Response:**
```json
{
  "model_name": "BrainGPT-7B-v0.0",
  "section": "abstract",
  "model_path": "/path/to/model.pth",
  "device": "cuda",
  "vocabulary_loaded": true,
  "vocabulary_size": 851,
  "embedding_service_stats": {
    "embeddings_loaded": 851,
    "indices_created": 1,
    "searches_performed": 42
  }
}
```

### Update Model Configuration

Change model settings and reload.

**Endpoint:** `POST /model`

**Request Body:**
```json
{
  "model_path": "/path/to/new/model.pth",
  "model_name": "BrainGPT-7B-v0.0",
  "section": "body",
  "device": "cuda"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Model configuration updated",
  "config": {
    "model_path": "/path/to/new/model.pth",
    "model_name": "BrainGPT-7B-v0.0",
    "section": "body",
    "device": "cuda"
  }
}
```

### List Available Vocabularies

Get information about available vocabulary types.

**Endpoint:** `GET /vocabularies`

**Response:**
```json
{
  "vocabularies": [
    {
      "type": "cogatlas_task-names",
      "description": "Cognitive Atlas task names (full)",
      "recommended": true,
      "size": 851,
      "available": true
    },
    {
      "type": "cogatlasred_task-names",
      "description": "Cognitive Atlas task names (reduced 88 tasks)",
      "recommended": false,
      "size": 88,
      "available": true
    }
  ],
  "default": "cogatlas_task-names"
}
```

## Python Client Usage

```python
from brain_researcher.services.neurokg.niclip.client import NICLIPClient

# Initialize client
client = NICLIPClient(base_url="http://localhost:8001")

# Predict cognitive processes
predictions = client.predict_cognitive_processes(
    "/path/to/brain_scan.nii.gz",
    top_k=10,
    use_bayes=True
)
print(predictions)

# Compute similarity
similarity = client.compute_similarity(
    "/path/to/brain_scan.nii.gz",
    "working memory"
)
print(f"Similarity: {similarity}")

# Search for similar concepts
similar_concepts = client.search_similar_concepts(
    "attention",
    vocabulary_type="cogatlas_task-names",
    top_k=5
)
for concept in similar_concepts:
    print(f"{concept['item']}: {concept['similarity']}")

# Close client
client.close()
```

## Interactive API Documentation

When the service is running, you can access interactive API documentation at:
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Error Responses

All endpoints return standard HTTP status codes:
- `200`: Success
- `400`: Bad request (invalid parameters)
- `404`: Resource not found
- `500`: Internal server error
- `503`: Service unavailable (model not loaded)

Error responses include a detail message:
```json
{
  "detail": "NIfTI file not found: /path/to/missing/file.nii"
}
```

## Performance Considerations

1. **Model Loading**: The first request may be slower as models are loaded into memory
2. **GPU Acceleration**: Use `device="cuda"` for faster inference if GPU is available
3. **Caching**: The service caches vocabulary embeddings and FAISS indices for fast repeated queries
4. **File Uploads**: Large NIfTI files may take time to upload; consider using file paths instead

## Environment Variables

- `NICLIP_DATA_PATH`: Path to NICLIP data directory (default: `/data/ECoG-foundation-model/mnndl_temp/niclip`)
- `NICLIP_PORT`: Service port (default: 8001)
- `NICLIP_HOST`: Service host (default: 0.0.0.0)

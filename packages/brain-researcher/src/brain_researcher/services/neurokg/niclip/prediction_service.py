"""
# NICLIP Prediction Service API Documentation

The NICLIP Prediction Service provides a RESTful API for neuroimaging-cognitive
language-image pretraining (NICLIP) functionality. This service enables brain
image analysis, cognitive process prediction, and similarity search between fMRI
data and text.

## Starting the Service (internal)

NiCLIP is treated as an in-process BR-KG capability. If you must run the HTTP
API locally, launch the FastAPI app directly:

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
  "timestamp": "2024-01-15T10:30:00"
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
    "model_name": "BrainGPT-7B-v0.2",
    "timestamp": "2024-01-15T10:30:00"
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
  "model_name": "BrainGPT-7B-v0.2"
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
    "model_name": "BrainGPT-7B-v0.2"
  }
}
```

### Get Model Info

Get information about the currently loaded model.

**Endpoint:** `GET /model`

**Response:**
```json
{
  "model_name": "BrainGPT-7B-v0.2",
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
  "model_name": "BrainGPT-7B-v0.2",
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
    "model_name": "BrainGPT-7B-v0.2",
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
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from brain_researcher.services.neurokg.niclip.engine import (
    NiclipEngine,
    NiclipEngineConfig,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NICLIP Prediction Service",
    description="Neuroimaging-Cognitive Language-Image Pretraining API",
    version="1.0.0",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine instance
engine: NiclipEngine | None = None

# Configuration
DEFAULT_MODEL_NAME = "BrainGPT-7B-v0.2"
DEFAULT_SECTION = "abstract"
NICLIP_DATA_PATH = os.environ.get(
    "NICLIP_EMBEDDINGS_PATH",
    os.environ.get("NICLIP_DATA_PATH", "/data/ECoG-foundation-model/mnndl_temp/niclip"),
)
NICLIP_MODEL_DIR = os.environ.get("NICLIP_MODEL_DIR")
NICLIP_MODEL_PATH = os.environ.get("NICLIP_MODEL_PATH")
NICLIP_FAISS_INDEX_PATH = os.environ.get("NICLIP_FAISS_INDEX_PATH")
NICLIP_DEVICE = os.environ.get("NICLIP_DEVICE") or os.environ.get("DEVICE")

# Keep a resolved path for diagnostics
_RESOLVED_MODEL_PATH: str | None = None


# Pydantic models
class PredictionRequest(BaseModel):
    """Request model for predictions"""

    nifti_path: str = Field(..., description="Path to NIfTI file")
    top_k: int = Field(10, description="Number of top predictions")
    use_bayes: bool = Field(True, description="Use Bayesian inference with priors")


class SimilarityRequest(BaseModel):
    """Request model for similarity computation"""

    nifti_path: str = Field(..., description="Path to NIfTI file")
    text: str = Field(..., description="Text to compare against")


class EmbeddingRequest(BaseModel):
    """Request model for text embedding"""

    text: str | list[str] = Field(..., description="Text or list of texts to encode")


class SearchRequest(BaseModel):
    """Request model for similarity search"""

    query: str = Field(..., description="Query term to search for")
    vocabulary_type: str = Field("cogatlas_task-names", description="Vocabulary type")
    top_k: int = Field(5, description="Number of similar items")


class ModelConfig(BaseModel):
    """Model configuration"""

    model_path: str | None = Field(None, description="Path to model checkpoint")
    model_name: str = Field(DEFAULT_MODEL_NAME, description="Model name")
    section: str = Field(DEFAULT_SECTION, description="Section to use")
    device: str | None = Field(None, description="Device (cuda, cpu, mps)")


class PredictionResponse(BaseModel):
    """Response model for predictions"""

    predictions: list[dict[str, str | float | int]]
    embedding_shape: list[int]
    metadata: dict[str, str | int | float]


class SimilarityResponse(BaseModel):
    """Response model for similarity"""

    similarity: float
    fmri_embedding_shape: list[int]
    text_embedding_shape: list[int]


class SearchResponse(BaseModel):
    """Response model for search"""

    query_item: str
    similar_items: list[dict[str, str | float]]
    total_vocabulary_size: int


# Initialization
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global engine, _RESOLVED_MODEL_PATH

    logger.info("Initializing NICLIP services...")

    cfg = NiclipEngineConfig.from_env()
    engine = NiclipEngine.get(cfg)
    _RESOLVED_MODEL_PATH = cfg.resolve_model_path()

    logger.info("NICLIP services initialized successfully")


# Endpoints
@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "NICLIP Prediction Service",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "predict": "/predict",
            "similarity": "/similarity",
            "encode": "/encode",
            "search": "/search",
            "analyze": "/analyze",
            "model": "/model",
            "health": "/health",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global engine
    if engine is None:
        engine = NiclipEngine.get(NiclipEngineConfig.from_env())
    payload = engine.status()
    payload.update(
        {
            "niclip_model_path": _RESOLVED_MODEL_PATH or payload.get("niclip_model_path"),
            "timestamp": datetime.now().isoformat(),
        }
    )
    return payload


@app.post("/predict", response_model=PredictionResponse)
async def predict_cognitive_processes(request: PredictionRequest):
    """
    Predict cognitive processes from a brain image.

    Args:
        request: Prediction request with NIfTI path and parameters

    Returns:
        Predictions with scores and metadata
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        # Validate file exists
        if not Path(request.nifti_path).exists():
            raise HTTPException(
                status_code=404, detail=f"NIfTI file not found: {request.nifti_path}"
            )

        # Get predictions
        predictions_df = engine.predict_from_nifti(
            request.nifti_path, top_k=request.top_k, use_bayes=request.use_bayes
        )

        # Get embedding for metadata
        embedding = engine.encode_fmri(request.nifti_path)

        # Convert DataFrame to list of dicts
        predictions = predictions_df.to_dict(orient="records")

        return PredictionResponse(
            predictions=predictions,
            embedding_shape=list(embedding.shape),
            metadata={
                "nifti_file": request.nifti_path,
                "top_k": request.top_k,
                "use_bayes": request.use_bayes,
                "model_name": engine.config.model_name,
                "timestamp": datetime.now().isoformat(),
            },
        )

    except Exception as e:
        logger.error(f"Error in prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/similarity", response_model=SimilarityResponse)
async def compute_similarity(request: SimilarityRequest):
    """
    Compute similarity between brain image and text.

    Args:
        request: Similarity request with NIfTI path and text

    Returns:
        Cosine similarity score and embedding shapes
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        # Validate file exists
        if not Path(request.nifti_path).exists():
            raise HTTPException(
                status_code=404, detail=f"NIfTI file not found: {request.nifti_path}"
            )

        # Compute similarity
        similarity = engine.similarity_brain_text(request.nifti_path, request.text)

        # Get embeddings for shapes
        fmri_embedding = engine.encode_fmri(request.nifti_path)
        text_embedding = engine.encode_text(request.text)

        return SimilarityResponse(
            similarity=similarity,
            fmri_embedding_shape=list(fmri_embedding.shape),
            text_embedding_shape=list(text_embedding.shape),
        )

    except Exception as e:
        logger.error(f"Error computing similarity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/encode")
async def encode_text(request: EmbeddingRequest):
    """
    Encode text into embeddings.

    Args:
        request: Text or list of texts to encode

    Returns:
        Embeddings and metadata
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        embeddings = engine.encode_text(request.text)

        return {
            "embeddings": embeddings.tolist(),
            "shape": list(embeddings.shape),
            "normalized": True,
            "model_name": engine.config.model_name,
        }

    except Exception as e:
        logger.error(f"Error encoding text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse)
async def search_similar_concepts(request: SearchRequest):
    """
    Search for similar cognitive concepts/tasks.

    Args:
        request: Search request with query and parameters

    Returns:
        Similar concepts with scores
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        # Load vocabulary index
        similar_items = engine.search(
            request.query,
            top_k=request.top_k,
            vocabulary_type=request.vocabulary_type,
        )

        try:
            vocab, _, _ = engine.get_vocabulary_index(
                request.vocabulary_type
            )
            total_vocab = len(vocab)
        except Exception:
            total_vocab = 0

        return SearchResponse(
            query_item=request.query,
            similar_items=similar_items[: request.top_k],
            total_vocabulary_size=total_vocab,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze")
async def analyze_uploaded_image(
    file: UploadFile = File(..., description="NIfTI file to analyze"),
    top_k: int = Query(10, description="Number of top predictions"),
    use_bayes: bool = Query(True, description="Use Bayesian inference"),
):
    """
    Analyze an uploaded NIfTI file.

    Args:
        file: Uploaded NIfTI file
        top_k: Number of top predictions
        use_bayes: Whether to use Bayesian inference

    Returns:
        Analysis results
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Check file extension
    if not file.filename.endswith((".nii", ".nii.gz")):
        raise HTTPException(
            status_code=400, detail="File must be a NIfTI file (.nii or .nii.gz)"
        )

    try:
        # Save uploaded file temporarily
        temp_path = Path(f"/tmp/{file.filename}")
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Analyze the file
        predictions_df = engine.predict_from_nifti(
            str(temp_path), top_k=top_k, use_bayes=use_bayes
        )

        # Get embedding
        embedding = engine.encode_fmri(str(temp_path))

        # Clean up
        temp_path.unlink()

        # Return results
        return {
            "filename": file.filename,
            "predictions": predictions_df.to_dict(orient="records"),
            "embedding_shape": list(embedding.shape),
            "top_prediction": predictions_df.iloc[0].to_dict()
            if len(predictions_df) > 0
            else None,
            "analysis_parameters": {
                "top_k": top_k,
                "use_bayes": use_bayes,
                "model_name": engine.config.model_name,
            },
        }

    except Exception as e:
        logger.error(f"Error analyzing uploaded file: {e}")
        # Clean up on error
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/model")
async def get_model_info():
    """Get information about the current model"""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    model = engine.get_model()
    if model is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    return {
        "model_name": model.model_name,
        "section": model.section,
        "model_path": model.model_path,
        "device": str(model.device),
        "vocabulary_loaded": model.vocabulary is not None,
        "vocabulary_size": len(model.vocabulary) if model.vocabulary else 0,
        "embedding_service_stats": engine.get_embedding_service().get_stats()
        if engine.get_embedding_service()
        else {},
    }


@app.post("/model")
async def update_model_config(config: ModelConfig):
    """Update model configuration and reload"""
    global engine, _RESOLVED_MODEL_PATH

    try:
        logger.info(f"Updating model configuration: {config}")

        base_cfg = engine.config if engine else NiclipEngineConfig.from_env()
        new_cfg = NiclipEngineConfig(
            data_path=base_cfg.data_path,
            model_dir=base_cfg.model_dir,
            model_path=config.model_path,
            faiss_index_path=base_cfg.faiss_index_path,
            model_name=config.model_name,
            section=config.section,
            device=config.device,
            vocabulary_type=base_cfg.vocabulary_type,
            index_type=base_cfg.index_type,
            normalize=base_cfg.normalize,
            use_gpu=base_cfg.use_gpu,
        )
        engine = NiclipEngine.get(new_cfg, force_reload=True)
        _RESOLVED_MODEL_PATH = new_cfg.resolve_model_path()

        return {
            "status": "success",
            "message": "Model configuration updated",
            "config": config.dict(),
        }

    except Exception as e:
        logger.error(f"Error updating model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vocabularies")
async def list_available_vocabularies():
    """List available vocabulary types"""
    if engine is None or not engine.get_embedding_service():
        raise HTTPException(status_code=503, detail="Embedding service not initialized")

    vocabulary_types = [
        {
            "type": "cogatlas_task-names",
            "description": "Cognitive Atlas task names (full)",
            "recommended": True,
        },
        {
            "type": "cogatlasred_task-names",
            "description": "Cognitive Atlas task names (reduced 88 tasks)",
            "recommended": False,
        },
        {
            "type": "cogatlas_task-definitions",
            "description": "Cognitive Atlas task definitions",
            "recommended": False,
        },
    ]

    # Check which ones are actually available
    available = []
    for vocab_info in vocabulary_types:
        try:
            vocab, _ = engine.get_embedding_service().load_vocabulary_embeddings(
                vocab_info["type"]
            )
            vocab_info["size"] = len(vocab)
            vocab_info["available"] = True
            available.append(vocab_info)
        except:
            vocab_info["available"] = False
            vocab_info["size"] = 0

    return {"vocabularies": available, "default": "cogatlas_task-names"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("NICLIP_PORT", 8001))
    host = os.environ.get("NICLIP_HOST", "0.0.0.0")

    print(f"Starting NICLIP Prediction Service on http://{host}:{port}")
    print(f"NICLIP data path: {NICLIP_DATA_PATH}")
    print(f"API docs available at: http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port)

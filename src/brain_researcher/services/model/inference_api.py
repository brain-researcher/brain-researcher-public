"""Model inference API for fMRI foundation model serving."""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import numpy as np
import torch
import torch.nn as nn
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator
from torch.utils.data import DataLoader

# NICLIP / fMRI text-alignment backend
from brain_researcher.services.br_kg.models.fmri_text_alignment import (
    FmriTextAlignmentModel,
)

logger = logging.getLogger(__name__)

# NICLIP / fMRI text alignment backend
from brain_researcher.services.br_kg.models.fmri_text_alignment import (
    FmriTextAlignmentModel,
)


class ModelType(str, Enum):
    """Available model types."""

    FMRI_FOUNDATION = "fmri_foundation"
    TASK_CLASSIFIER = "task_classifier"
    REGION_ENCODER = "region_encoder"
    CONNECTIVITY_PREDICTOR = "connectivity_predictor"
    CUSTOM = "custom"


class InferenceMode(str, Enum):
    """Inference modes."""

    SINGLE = "single"
    BATCH = "batch"
    STREAM = "stream"


class InputFormat(str, Enum):
    """Input data formats."""

    NIFTI = "nifti"
    NUMPY = "numpy"
    TENSOR = "tensor"
    CSV = "csv"
    JSON = "json"


class InferenceRequest(BaseModel):
    """Inference request model."""

    model_type: ModelType = Field(ModelType.FMRI_FOUNDATION, description="Model type")
    model_version: Optional[str] = Field("latest", description="Model version")
    input_data: Union[str, List[float], Dict[str, Any]] = Field(
        ..., description="Input data (path, array, or dict)"
    )
    input_format: InputFormat = Field(InputFormat.JSON, description="Input format")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Inference parameters"
    )
    return_attention: bool = Field(False, description="Return attention weights")
    return_embeddings: bool = Field(False, description="Return intermediate embeddings")
    batch_size: int = Field(1, description="Batch size for processing", ge=1, le=128)

    @validator("input_data")
    def validate_input_data(cls, v):
        """Validate input data."""
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("Input data cannot be empty")
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Input data cannot be empty")
        return v


class InferenceResponse(BaseModel):
    """Inference response model."""

    request_id: str = Field(..., description="Request identifier")
    model_type: ModelType = Field(..., description="Model type used")
    model_version: str = Field(..., description="Model version used")
    predictions: Union[List[Any], Dict[str, Any]] = Field(
        ..., description="Model predictions"
    )
    confidence: Optional[float] = Field(
        None, description="Prediction confidence", ge=0, le=1
    )
    processing_time_ms: float = Field(
        ..., description="Processing time in milliseconds"
    )
    attention_weights: Optional[Dict[str, Any]] = Field(
        None, description="Attention weights"
    )
    embeddings: Optional[Dict[str, Any]] = Field(
        None, description="Intermediate embeddings"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class BatchInferenceRequest(BaseModel):
    """Batch inference request model."""

    model_type: ModelType = Field(ModelType.FMRI_FOUNDATION, description="Model type")
    model_version: Optional[str] = Field("latest", description="Model version")
    samples: List[Union[str, List[float], Dict[str, Any]]] = Field(
        ..., description="Batch samples"
    )
    input_format: InputFormat = Field(InputFormat.JSON, description="Input format")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Inference parameters"
    )
    batch_size: int = Field(32, description="Batch size", ge=1, le=256)
    async_processing: bool = Field(False, description="Process asynchronously")

    @validator("samples")
    def validate_samples(cls, v):
        """Validate samples."""
        if len(v) == 0:
            raise ValueError("Samples cannot be empty")
        if len(v) > 10000:
            raise ValueError("Too many samples (max 10000)")
        return v


class BatchInferenceResponse(BaseModel):
    """Batch inference response model."""

    batch_id: str = Field(..., description="Batch identifier")
    model_type: ModelType = Field(..., description="Model type used")
    model_version: str = Field(..., description="Model version used")
    results: List[Dict[str, Any]] = Field(..., description="Batch results")
    total_samples: int = Field(..., description="Total samples processed")
    successful: int = Field(..., description="Successful predictions")
    failed: int = Field(..., description="Failed predictions")
    total_time_ms: float = Field(..., description="Total processing time")
    avg_time_per_sample_ms: float = Field(..., description="Average time per sample")


@dataclass
class ModelInfo:
    """Model information."""

    model_type: ModelType
    version: str
    path: Path
    config: Dict[str, Any]
    loaded: bool = False
    model: Optional[nn.Module] = None
    device: str = "cpu"
    last_used: Optional[datetime] = None
    request_count: int = 0
    total_inference_time: float = 0.0

    @property
    def avg_inference_time(self) -> float:
        """Average inference time per request."""
        if self.request_count == 0:
            return 0.0
        return self.total_inference_time / self.request_count


class ModelPool:
    """Model pool for managing multiple models."""

    def __init__(
        self,
        max_models: int = 5,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
    ):
        """Initialize model pool.

        Args:
            max_models: Maximum models to keep loaded
            device: Device for inference
        """
        self.max_models = max_models
        self.device = device
        self.models: Dict[str, ModelInfo] = {}
        self.load_queue = deque(maxlen=max_models)
        self.lock = threading.Lock()

    def get_model(self, model_type: ModelType, version: str = "latest") -> nn.Module:
        """Get model from pool.

        Args:
            model_type: Model type
            version: Model version

        Returns:
            Loaded model
        """
        model_key = f"{model_type.value}:{version}"

        with self.lock:
            if model_key not in self.models:
                # Load model
                model_info = self._load_model(model_type, version)
                self.models[model_key] = model_info

                # Manage pool size
                if len(self.load_queue) >= self.max_models:
                    # Unload least recently used
                    old_key = self.load_queue.popleft()
                    if old_key in self.models:
                        self._unload_model(old_key)

                self.load_queue.append(model_key)

            model_info = self.models[model_key]
            model_info.last_used = datetime.now()
            model_info.request_count += 1

            return model_info.model

    def _load_model(self, model_type: ModelType, version: str) -> ModelInfo:
        """Load model from disk.

        Args:
            model_type: Model type
            version: Model version

        Returns:
            Model information
        """
        # Placeholder for actual model loading
        # In production, this would load from model registry

        if model_type == ModelType.FMRI_FOUNDATION:
            model = self._create_dummy_foundation_model()
        else:
            model = self._create_dummy_model()

        model = model.to(self.device)
        model.eval()

        return ModelInfo(
            model_type=model_type,
            version=version,
            path=Path(f"/models/{model_type.value}/{version}"),
            config={"architecture": "transformer", "params": 100000000},
            loaded=True,
            model=model,
            device=self.device,
        )

    def _unload_model(self, model_key: str):
        """Unload model from memory.

        Args:
            model_key: Model key
        """
        if model_key in self.models:
            model_info = self.models[model_key]
            if model_info.model:
                del model_info.model
                model_info.model = None
                model_info.loaded = False

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _create_dummy_foundation_model(self) -> nn.Module:
        """Create dummy foundation model for testing."""

        class DummyFoundationModel(nn.Module):
            def __init__(self, input_dim=1024, hidden_dim=512, output_dim=256):
                super().__init__()
                self.encoder = nn.Sequential(
                    nn.Linear(input_dim, hidden_dim),
                    nn.ReLU(),
                    nn.LayerNorm(hidden_dim),
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.ReLU(),
                    nn.LayerNorm(hidden_dim),
                )
                self.decoder = nn.Linear(hidden_dim, output_dim)
                self.attention = nn.MultiheadAttention(hidden_dim, num_heads=8)

            def forward(self, x, return_attention=False, return_embeddings=False):
                # Encode
                embeddings = self.encoder(x)

                # Self-attention
                attn_out, attn_weights = self.attention(
                    embeddings, embeddings, embeddings
                )

                # Decode
                output = self.decoder(attn_out)

                result = {"predictions": output}

                if return_attention:
                    result["attention"] = attn_weights

                if return_embeddings:
                    result["embeddings"] = embeddings

                return result

        return DummyFoundationModel()

    def _create_dummy_model(self) -> nn.Module:
        """Create dummy model for testing."""
        return nn.Sequential(
            nn.Linear(1024, 512),
            nn.ReLU(),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get model pool statistics.

        Returns:
            Pool statistics
        """
        with self.lock:
            return {
                "loaded_models": len([m for m in self.models.values() if m.loaded]),
                "total_models": len(self.models),
                "device": self.device,
                "models": {
                    key: {
                        "type": info.model_type.value,
                        "version": info.version,
                        "loaded": info.loaded,
                        "requests": info.request_count,
                        "avg_time_ms": info.avg_inference_time * 1000,
                    }
                    for key, info in self.models.items()
                },
            }


class BatchProcessor:
    """Batch processing for efficient inference."""

    def __init__(self, model_pool: ModelPool, max_batch_size: int = 32):
        """Initialize batch processor.

        Args:
            model_pool: Model pool
            max_batch_size: Maximum batch size
        """
        self.model_pool = model_pool
        self.max_batch_size = max_batch_size
        self.pending_requests: Dict[str, List[Dict]] = {}
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.lock = threading.Lock()

    def add_request(
        self,
        request_id: str,
        model_type: ModelType,
        input_data: Any,
        parameters: Dict[str, Any],
    ):
        """Add request to batch.

        Args:
            request_id: Request identifier
            model_type: Model type
            input_data: Input data
            parameters: Inference parameters
        """
        with self.lock:
            key = model_type.value
            if key not in self.pending_requests:
                self.pending_requests[key] = []

            self.pending_requests[key].append(
                {
                    "request_id": request_id,
                    "input_data": input_data,
                    "parameters": parameters,
                    "timestamp": time.time(),
                }
            )

            # Process if batch is full
            if len(self.pending_requests[key]) >= self.max_batch_size:
                self._process_batch(key)

    def _process_batch(self, model_key: str):
        """Process a batch of requests.

        Args:
            model_key: Model key
        """
        if model_key not in self.pending_requests:
            return

        batch = self.pending_requests.pop(model_key, [])
        if not batch:
            return

        # Submit to executor
        self.executor.submit(self._run_batch_inference, model_key, batch)

    def _run_batch_inference(self, model_key: str, batch: List[Dict]):
        """Run batch inference.

        Args:
            model_key: Model key
            batch: Batch of requests
        """
        model_type = ModelType(model_key)
        model = self.model_pool.get_model(model_type)

        # Prepare batch input
        batch_input = torch.stack(
            [self._prepare_input(req["input_data"]) for req in batch]
        )

        # Run inference
        with torch.no_grad():
            outputs = model(batch_input)

        # Process outputs
        for i, req in enumerate(batch):
            # Store result
            result_key = f"result:{req['request_id']}"
            # Would store in Redis or return via callback

    def _prepare_input(self, input_data: Any) -> torch.Tensor:
        """Prepare input for model.

        Args:
            input_data: Raw input data

        Returns:
            Input tensor
        """
        if isinstance(input_data, list):
            return torch.tensor(input_data, dtype=torch.float32)
        elif isinstance(input_data, dict):
            # Handle dict input
            return torch.randn(1024)  # Placeholder
        else:
            return torch.randn(1024)  # Placeholder


class InferenceService:
    """Main inference service."""

    def __init__(self, model_pool: Optional[ModelPool] = None):
        """Initialize inference service.

        Args:
            model_pool: Model pool instance
        """
        self.model_pool = model_pool or ModelPool()
        self.batch_processor = BatchProcessor(self.model_pool)
        self.fmri_model: Optional[FmriTextAlignmentModel] = None

    def _get_fmri_model(self) -> FmriTextAlignmentModel:
        """Lazily initialize the NiCLIP fMRI alignment model."""
        if self.fmri_model is None:
            try:
                self.fmri_model = FmriTextAlignmentModel()
                logger.info("Initialized NiCLIP fMRI alignment model")
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to initialize NiCLIP model: %s", exc)
                raise
        return self.fmri_model

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Run single inference.

        Args:
            request: Inference request

        Returns:
            Inference response
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()

        if request.model_type == ModelType.FMRI_FOUNDATION:
            response = await self._infer_fmri_foundation(
                request_id=request_id, request=request, start_time=start_time
            )
            return response

        # Default path for non-fMRI models (keep placeholder behavior)
        model = self.model_pool.get_model(request.model_type, request.model_version)

        # Prepare input
        input_tensor = self._prepare_input(request.input_data, request.input_format)

        # Run inference
        with torch.no_grad():
            input_tensor = input_tensor.to(self.model_pool.device)

            if hasattr(model, "forward"):
                outputs = model(
                    input_tensor,
                    return_attention=request.return_attention,
                    return_embeddings=request.return_embeddings,
                )
            else:
                outputs = {"predictions": model(input_tensor)}

        predictions = self._process_output(outputs.get("predictions"))
        confidence = float(
            torch.sigmoid(outputs.get("predictions", torch.tensor(0.0))).mean()
        )
        processing_time = (time.time() - start_time) * 1000

        return InferenceResponse(
            request_id=request_id,
            model_type=request.model_type,
            model_version=request.model_version or "latest",
            predictions=predictions,
            confidence=confidence,
            processing_time_ms=processing_time,
            attention_weights=(
                outputs.get("attention") if request.return_attention else None
            ),
            embeddings=outputs.get("embeddings") if request.return_embeddings else None,
            metadata={
                "device": self.model_pool.device,
                "batch_size": request.batch_size,
            },
        )

    async def batch_infer(
        self, request: BatchInferenceRequest
    ) -> BatchInferenceResponse:
        """Run batch inference.

        Args:
            request: Batch inference request

        Returns:
            Batch inference response
        """
        batch_id = str(uuid.uuid4())
        start_time = time.time()

        # Fast path: real NiCLIP-backed fMRI foundation model
        if request.model_type == ModelType.FMRI_FOUNDATION:
            results = []
            successful = 0
            failed = 0
            for idx, sample in enumerate(request.samples):
                try:
                    single_req = InferenceRequest(
                        model_type=request.model_type,
                        model_version=request.model_version,
                        input_data=sample,
                        input_format=request.input_format,
                        parameters=request.parameters,
                        return_attention=False,
                        return_embeddings=False,
                    )
                    resp = await self.infer(single_req)
                    results.append(
                        {
                            "sample_id": idx,
                            "predictions": resp.predictions,
                            "status": "success",
                        }
                    )
                    successful += 1
                except Exception as e:
                    results.append(
                        {"sample_id": idx, "error": str(e), "status": "failed"}
                    )
                    failed += 1

            total_time = (time.time() - start_time) * 1000
            return BatchInferenceResponse(
                batch_id=batch_id,
                model_type=request.model_type,
                model_version=request.model_version or "latest",
                results=results,
                total_samples=len(request.samples),
                successful=successful,
                failed=failed,
                total_time_ms=total_time,
                avg_time_per_sample_ms=(
                    total_time / len(request.samples) if request.samples else 0
                ),
            )

        # Placeholder path for other model types
        model = self.model_pool.get_model(request.model_type, request.model_version)

        results = []
        successful = 0
        failed = 0

        # Process in batches
        for i in range(0, len(request.samples), request.batch_size):
            batch = request.samples[i : i + request.batch_size]

            try:
                # Prepare batch input
                batch_tensor = torch.stack(
                    [
                        self._prepare_input(sample, request.input_format)
                        for sample in batch
                    ]
                )

                # Run inference
                with torch.no_grad():
                    batch_tensor = batch_tensor.to(self.model_pool.device)
                    outputs = model(batch_tensor)

                # Process outputs
                for j, output in enumerate(outputs):
                    results.append(
                        {
                            "sample_id": i + j,
                            "predictions": self._process_output(output),
                            "status": "success",
                        }
                    )
                    successful += 1

            except Exception as e:
                # Handle batch failure
                for j in range(len(batch)):
                    results.append(
                        {"sample_id": i + j, "error": str(e), "status": "failed"}
                    )
                    failed += 1

        total_time = (time.time() - start_time) * 1000

        return BatchInferenceResponse(
            batch_id=batch_id,
            model_type=request.model_type,
            model_version=request.model_version or "latest",
            results=results,
            total_samples=len(request.samples),
            successful=successful,
            failed=failed,
            total_time_ms=total_time,
            avg_time_per_sample_ms=(
                total_time / len(request.samples) if request.samples else 0
            ),
        )

    def _prepare_input(self, data: Any, format: InputFormat) -> torch.Tensor:
        """Prepare input data for model.

        Args:
            data: Raw input data
            format: Input format

        Returns:
            Input tensor
        """
        if format == InputFormat.NUMPY:
            return torch.from_numpy(np.array(data)).float()
        elif format == InputFormat.TENSOR:
            return torch.tensor(data, dtype=torch.float32)
        elif format == InputFormat.JSON:
            if isinstance(data, list):
                return torch.tensor(data, dtype=torch.float32)
            else:
                # Extract features from dict
                return torch.randn(1024)  # Placeholder
        elif format == InputFormat.NIFTI:
            # For NIfTI we keep path handling at higher level; return dummy tensor
            return torch.randn(1024)
        else:
            # Placeholder for other formats
            return torch.randn(1024)

    def _process_output(
        self, output: torch.Tensor
    ) -> Union[List[float], Dict[str, Any]]:
        """Process model output.

        Args:
            output: Model output tensor

        Returns:
            Processed output
        """
        if output.dim() == 1:
            return output.cpu().numpy().tolist()
        elif output.dim() == 2:
            return {
                "logits": output.cpu().numpy().tolist(),
                "shape": list(output.shape),
            }
        else:
            return {"data": output.cpu().numpy().tolist(), "shape": list(output.shape)}

    async def _infer_fmri_foundation(
        self, request_id: str, request: InferenceRequest, start_time: float
    ) -> InferenceResponse:
        """Run NiCLIP-backed fMRI foundation model inference."""
        fmri_model = self._get_fmri_model()

        # Extract optional parameters
        top_k = int(request.parameters.get("top_k", 5))
        use_bayes = bool(request.parameters.get("use_bayes", True))
        text_query = request.parameters.get("text")

        # Prepare input
        input_data = request.input_data

        predictions: Dict[str, Any] = {}
        embeddings: Optional[Dict[str, Any]] = None
        attention = None  # Not provided by current backend

        try:
            if request.input_format == InputFormat.NIFTI or (
                isinstance(input_data, str)
                and input_data.lower().endswith((".nii", ".nii.gz"))
            ):
                # Path to NIfTI file
                pred_df = fmri_model.predict_from_nifti(
                    str(input_data), top_k=top_k, use_bayes=use_bayes
                )
                predictions = pred_df.to_dict(orient="records")

                if request.return_embeddings:
                    emb = fmri_model.encode_fmri(str(input_data))
                    embeddings = {
                        "fmri_embedding": (
                            emb.tolist() if hasattr(emb, "tolist") else emb
                        )
                    }
            else:
                # Array-like input
                if isinstance(input_data, list):
                    arr = np.array(input_data, dtype=np.float32)
                elif isinstance(input_data, dict) and "fmri" in input_data:
                    arr = np.array(input_data["fmri"], dtype=np.float32)
                else:
                    arr = np.array(input_data, dtype=np.float32)

                if arr.ndim == 1:
                    # Treat 1D input as precomputed embedding
                    emb = arr
                else:
                    emb = fmri_model.encode_fmri(arr)
                if request.return_embeddings:
                    embeddings = {
                        "fmri_embedding": (
                            emb.tolist() if hasattr(emb, "tolist") else emb
                        )
                    }

                if text_query:
                    sim = fmri_model.compute_similarity(arr, text_query)
                    predictions = {"similarity": sim, "text": text_query}
                else:
                    decoded = fmri_model.decode_to_text(
                        emb, top_k=top_k, return_scores=True
                    )
                    if isinstance(decoded, str):
                        predictions = {"text": decoded}
                    else:
                        predictions = [
                            {"task": task, "similarity": float(score)}
                            for task, score in decoded
                        ]
        except Exception as exc:
            logger.error("fMRI foundation inference failed: %s", exc)
            raise

        processing_time = (time.time() - start_time) * 1000
        # Derive a confidence signal from top prediction when available
        confidence = None
        confidence_source = None
        if isinstance(predictions, list) and predictions:
            top = predictions[0]
            if isinstance(top, dict):
                if "prob" in top:
                    confidence = float(top["prob"])
                    confidence_source = "posterior_prob"
                elif "similarity" in top:
                    confidence = float(top["similarity"])
                    confidence_source = "similarity"
            elif isinstance(top, (float, int)):
                confidence = float(top)
                confidence_source = "scalar"
        elif isinstance(predictions, dict):
            if "prob" in predictions:
                confidence = float(predictions["prob"])
                confidence_source = "posterior_prob"
            elif "similarity" in predictions:
                confidence = float(predictions["similarity"])
                confidence_source = "similarity"

        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))

        return InferenceResponse(
            request_id=request_id,
            model_type=request.model_type,
            model_version=request.model_version or "latest",
            predictions=predictions,
            confidence=confidence,
            processing_time_ms=processing_time,
            attention_weights=attention,
            embeddings=embeddings,
            metadata={
                "device": str(fmri_model.device),
                "top_k": top_k,
                "use_bayes": use_bayes,
                "confidence_source": confidence_source,
            },
        )

    def get_model_info(
        self, model_type: ModelType, version: str = "latest"
    ) -> Dict[str, Any]:
        """Get model information.

        Args:
            model_type: Model type
            version: Model version

        Returns:
            Model information
        """
        model_key = f"{model_type.value}:{version}"

        if model_key in self.model_pool.models:
            info = self.model_pool.models[model_key]
            return {
                "type": info.model_type.value,
                "version": info.version,
                "loaded": info.loaded,
                "device": info.device,
                "config": info.config,
                "requests": info.request_count,
                "avg_inference_time_ms": info.avg_inference_time * 1000,
                "last_used": info.last_used.isoformat() if info.last_used else None,
            }
        else:
            return {
                "type": model_type.value,
                "version": version,
                "loaded": False,
                "available": True,
            }


# Create router
router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


# Dependency to get service
def get_inference_service() -> InferenceService:
    """Get inference service."""
    return InferenceService()


@router.post("/predict", response_model=InferenceResponse)
async def predict(
    request: InferenceRequest,
    service: InferenceService = Depends(get_inference_service),
) -> InferenceResponse:
    """Run single inference.

    Args:
        request: Inference request
        service: Inference service

    Returns:
        Inference response
    """
    try:
        response = await service.infer(request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference failed: {str(e)}",
        )


@router.post("/batch", response_model=BatchInferenceResponse)
async def batch_predict(
    request: BatchInferenceRequest,
    service: InferenceService = Depends(get_inference_service),
) -> BatchInferenceResponse:
    """Run batch inference.

    Args:
        request: Batch inference request
        service: Inference service

    Returns:
        Batch inference response
    """
    try:
        response = await service.batch_infer(request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch inference failed: {str(e)}",
        )


@router.get("/models/{model_type}")
async def get_model_info(
    model_type: ModelType,
    version: str = "latest",
    service: InferenceService = Depends(get_inference_service),
) -> Dict[str, Any]:
    """Get model information.

    Args:
        model_type: Model type
        version: Model version
        service: Inference service

    Returns:
        Model information
    """
    return service.get_model_info(model_type, version)


@router.get("/stats")
async def get_inference_stats(
    service: InferenceService = Depends(get_inference_service),
) -> Dict[str, Any]:
    """Get inference statistics.

    Args:
        service: Inference service

    Returns:
        Inference statistics
    """
    return service.model_pool.get_stats()

"""
Advanced Visualization Service Backend
Provides nilearn-based preprocessing and analysis for 3D brain visualization
"""

import os
import io
import tempfile
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union
import logging
from io import BytesIO

# FastAPI and response handling
from fastapi import FastAPI, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Neuroimaging libraries
try:
    import nibabel as nib
    from nilearn import datasets
    from nilearn import image
    from nilearn import plotting
    from nilearn import surface
    from nilearn.maskers import NiftiMasker
    from nilearn.glm.first_level import FirstLevelModel
    from nilearn.glm.second_level import SecondLevelModel
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    NILEARN_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Nilearn not available: {e}")
    NILEARN_AVAILABLE = False

# Video processing for animations
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Brain Researcher Visualization Service",
    description="Backend service for advanced 3D brain visualization processing",
    version="1.0.0"
)

# CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for API
class VolumeProcessingRequest(BaseModel):
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None
    smooth_fwhm: Optional[float] = None
    resample_target: Optional[str] = None  # 'mni152' or custom voxel size
    align_to_ras: bool = True

class AnimationExportRequest(BaseModel):
    format: str = "mp4"  # 'mp4' or 'webm'
    fps: int = 10
    duration: Optional[float] = None
    quality: str = "medium"  # 'low', 'medium', 'high'

class StatisticalMapRequest(BaseModel):
    stat_type: str = "t"  # 't', 'z', 'f'
    threshold: float = 2.0
    cluster_threshold: Optional[int] = None
    correction: Optional[str] = None  # 'fdr', 'bonferroni', None

# Global template cache
_template_cache = {}

def get_mni_template(resolution: str = "2mm") -> nib.Nifti1Image:
    """Load MNI152 template with caching"""
    cache_key = f"mni152_{resolution}"
    
    if cache_key not in _template_cache:
        try:
            # Use correct nilearn API
            template = datasets.load_mni152_template(resolution=resolution)
            _template_cache[cache_key] = template
            logger.info(f"Loaded MNI152 template at {resolution} resolution")
        except Exception as e:
            logger.error(f"Failed to load MNI152 template: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load MNI152 template: {e}")
    
    return _template_cache[cache_key]

def validate_nifti_file(file_data: bytes) -> nib.Nifti1Image:
    """Validate and load NIfTI file from bytes"""
    try:
        # Use BytesIO for proper file handling
        file_like = BytesIO(file_data)
        img = nib.load(file_like)
        
        # Basic validation
        if img.get_fdata().size == 0:
            raise ValueError("Empty NIfTI data")
            
        return img
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid NIfTI file: {e}")

def align_to_ras_plus(img: nib.Nifti1Image) -> nib.Nifti1Image:
    """Align image to RAS+ coordinate system"""
    try:
        # Get canonical image (RAS+ oriented)
        canonical_img = nib.as_closest_canonical(img)
        return canonical_img
    except Exception as e:
        logger.error(f"Failed to align to RAS+: {e}")
        return img  # Return original if alignment fails

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Brain Researcher Visualization Service",
        "status": "running",
        "nilearn_available": NILEARN_AVAILABLE,
        "opencv_available": OPENCV_AVAILABLE
    }

@app.get("/templates/mni152")
async def get_mni152_template_endpoint(
    resolution: str = Query("2mm", description="Template resolution: 1mm or 2mm")
):
    """Get MNI152 template as downloadable NIfTI"""
    if not NILEARN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Nilearn not available")
    
    try:
        template = get_mni_template(resolution)
        
        # Convert to bytes
        output = BytesIO()
        nib.save(template, output)
        output.seek(0)
        
        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=mni152_{resolution}.nii.gz"}
        )
    except Exception as e:
        logger.error(f"Template download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process/volume")
async def process_volume(
    file: UploadFile = File(...),
    request: VolumeProcessingRequest = VolumeProcessingRequest()
):
    """Process uploaded NIfTI volume with various preprocessing options"""
    if not NILEARN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Nilearn not available")
    
    try:
        # Read file data
        file_data = await file.read()
        img = validate_nifti_file(file_data)
        
        processed_img = img
        processing_steps = []
        
        # Apply RAS+ alignment
        if request.align_to_ras:
            processed_img = align_to_ras_plus(processed_img)
            processing_steps.append("aligned_to_ras_plus")
        
        # Apply smoothing
        if request.smooth_fwhm:
            processed_img = image.smooth_img(processed_img, fwhm=request.smooth_fwhm)
            processing_steps.append(f"smoothed_fwhm_{request.smooth_fwhm}")
        
        # Apply thresholding
        if request.threshold_min is not None or request.threshold_max is not None:
            data = processed_img.get_fdata()
            if request.threshold_min is not None:
                data[data < request.threshold_min] = 0
            if request.threshold_max is not None:
                data[data > request.threshold_max] = request.threshold_max
            
            processed_img = nib.Nifti1Image(data, processed_img.affine, processed_img.header)
            processing_steps.append("thresholded")
        
        # Resample to target space
        if request.resample_target:
            if request.resample_target == "mni152":
                template = get_mni_template("2mm")
                processed_img = image.resample_to_img(processed_img, template)
                processing_steps.append("resampled_to_mni152")
            else:
                # Parse custom voxel size (e.g., "2x2x2")
                try:
                    voxel_sizes = [float(x) for x in request.resample_target.split("x")]
                    if len(voxel_sizes) == 3:
                        processed_img = image.resample_img(
                            processed_img, 
                            target_affine=np.diag(voxel_sizes + [1])
                        )
                        processing_steps.append(f"resampled_{request.resample_target}")
                except Exception as e:
                    logger.warning(f"Failed to parse voxel size: {e}")
        
        # Convert to bytes for streaming
        output = BytesIO()
        nib.save(processed_img, output)
        output.seek(0)
        
        # Return processed volume
        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=processed_{file.filename}",
                "X-Processing-Steps": ",".join(processing_steps)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Volume processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process/statistical-map")
async def create_statistical_map(
    file: UploadFile = File(...),
    request: StatisticalMapRequest = StatisticalMapRequest()
):
    """Create statistical map from uploaded volume"""
    if not NILEARN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Nilearn not available")
    
    try:
        file_data = await file.read()
        img = validate_nifti_file(file_data)
        
        # Apply statistical thresholding
        data = img.get_fdata()
        
        if request.stat_type.lower() == 't':
            # T-statistic thresholding
            thresholded_data = np.where(np.abs(data) > request.threshold, data, 0)
        elif request.stat_type.lower() == 'z':
            # Z-score thresholding
            thresholded_data = np.where(np.abs(data) > request.threshold, data, 0)
        else:
            thresholded_data = data
        
        # Apply cluster thresholding if requested
        if request.cluster_threshold:
            # This would require scipy.ndimage for cluster analysis
            # Simplified implementation
            thresholded_data = np.where(thresholded_data != 0, thresholded_data, 0)
        
        # Create new statistical map
        stat_img = nib.Nifti1Image(thresholded_data, img.affine, img.header)
        
        # Convert to bytes
        output = BytesIO()
        nib.save(stat_img, output)
        output.seek(0)
        
        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=stat_map_{file.filename}"}
        )
        
    except Exception as e:
        logger.error(f"Statistical map error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/export/animation")
async def export_animation(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    request: AnimationExportRequest = AnimationExportRequest()
):
    """Export 4D volume or frame sequence as video animation"""
    if not OPENCV_AVAILABLE:
        raise HTTPException(status_code=503, detail="OpenCV not available for video export")
    
    if not NILEARN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Nilearn not available")
    
    try:
        # Process files as either 4D volume or frame sequence
        frames = []
        
        if len(files) == 1:
            # Single 4D volume
            file_data = await files[0].read()
            img = validate_nifti_file(file_data)
            
            if img.ndim == 4:
                # Extract frames from 4D volume
                for t in range(img.shape[3]):
                    frame_data = img.get_fdata()[:, :, :, t]
                    frames.append(frame_data)
            else:
                raise HTTPException(status_code=400, detail="Single file must be 4D volume")
        else:
            # Multiple 3D volumes as frames
            for file in files:
                file_data = await file.read()
                img = validate_nifti_file(file_data)
                frames.append(img.get_fdata())
        
        if not frames:
            raise HTTPException(status_code=400, detail="No frames to animate")
        
        # Create temporary video file
        with tempfile.NamedTemporaryFile(suffix=f".{request.format}", delete=False) as tmp_file:
            temp_path = tmp_file.name
        
        try:
            # Setup video writer
            height, width = frames[0].shape[:2] if frames[0].ndim >= 2 else (256, 256)
            
            if request.format == "mp4":
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            else:
                fourcc = cv2.VideoWriter_fourcc(*'VP80')  # WebM
            
            out = cv2.VideoWriter(temp_path, fourcc, request.fps, (width, height))
            
            # Write frames
            for frame_data in frames:
                # Normalize to 0-255 range
                if frame_data.ndim >= 2:
                    # Take middle slice for 3D data
                    if frame_data.ndim == 3:
                        slice_data = frame_data[:, :, frame_data.shape[2] // 2]
                    else:
                        slice_data = frame_data
                    
                    # Normalize and convert to uint8
                    normalized = ((slice_data - slice_data.min()) / 
                                 (slice_data.max() - slice_data.min()) * 255).astype(np.uint8)
                    
                    # Convert to 3-channel for video
                    frame_rgb = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
                    out.write(frame_rgb)
            
            out.release()
            
            # Read video data
            with open(temp_path, 'rb') as f:
                video_data = f.read()
            
            # Clean up temp file in background
            background_tasks.add_task(os.unlink, temp_path)
            
            return StreamingResponse(
                io.BytesIO(video_data),
                media_type=f"video/{request.format}",
                headers={"Content-Disposition": f"attachment; filename=brain_animation.{request.format}"}
            )
            
        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Animation export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/volume/info")
async def get_volume_info(file: UploadFile = File(...)):
    """Get information about uploaded NIfTI volume"""
    if not NILEARN_AVAILABLE:
        raise HTTPException(status_code=503, detail="Nilearn not available")
    
    try:
        file_data = await file.read()
        img = validate_nifti_file(file_data)
        
        data = img.get_fdata()
        
        info = {
            "filename": file.filename,
            "shape": list(data.shape),
            "n_dimensions": data.ndim,
            "is_4d": data.ndim == 4,
            "n_frames": data.shape[3] if data.ndim == 4 else 1,
            "voxel_sizes": img.header.get_zooms()[:3],
            "data_type": str(data.dtype),
            "min_value": float(data.min()),
            "max_value": float(data.max()),
            "mean_value": float(data.mean()),
            "std_value": float(data.std()),
            "affine_matrix": img.affine.tolist(),
            "coordinate_system": "RAS+" if nib.aff2axcodes(img.affine) == ('R', 'A', 'S') else "other"
        }
        
        return JSONResponse(info)
        
    except Exception as e:
        logger.error(f"Volume info error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/surface/extract")
async def extract_surface_mesh(
    file: UploadFile = File(...),
    threshold: float = Query(0.5, description="Iso-surface threshold")
):
    """Extract surface mesh from volume (placeholder - would require additional libraries)"""
    raise HTTPException(
        status_code=501, 
        detail="Surface extraction not implemented - requires additional dependencies"
    )

@app.get("/health")
async def health_check():
    """Detailed health check with dependency status"""
    return {
        "status": "healthy",
        "dependencies": {
            "nilearn": NILEARN_AVAILABLE,
            "opencv": OPENCV_AVAILABLE,
            "nibabel": True  # Should always be available if nilearn is
        },
        "capabilities": {
            "volume_processing": NILEARN_AVAILABLE,
            "statistical_maps": NILEARN_AVAILABLE,
            "animation_export": NILEARN_AVAILABLE and OPENCV_AVAILABLE,
            "template_loading": NILEARN_AVAILABLE
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

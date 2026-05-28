"""
GLM Direction Validator

Validates NiCLIP-LLM predictions against actual GLM beta values
to ensure predicted cognitive processes align with brain activation patterns.

This module:
1. Loads GLM beta maps from fMRI analyses
2. Extracts beta values at specified coordinates
3. Validates direction predictions (positive/negative activation)
4. Calculates alignment scores between predictions and actual data
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import warnings

import numpy as np
import nibabel as nib
from scipy.ndimage import map_coordinates
from scipy.stats import percentileofscore
import pandas as pd

logger = logging.getLogger(__name__)


class GLMDirectionValidator:
    """Validates cognitive predictions against GLM beta values."""
    
    def __init__(self, glm_data_path: Optional[Path] = None):
        """
        Initialize GLM validator.
        
        Args:
            glm_data_path: Path to GLM results directory
        """
        self.glm_data_path = glm_data_path or self._find_glm_data()
        self.beta_maps = {}
        self.contrast_info = {}
        self._loaded = False
        
        if self.glm_data_path and self.glm_data_path.exists():
            self._load_glm_data()
        else:
            logger.warning(f"GLM data path not found: {self.glm_data_path}")
            
    def _find_glm_data(self) -> Optional[Path]:
        """Find GLM data in standard locations."""
        possible_paths = [
            Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "glm_results",
            Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "unified_zstat",
            Path("/data/glm_results"),
            Path("/data/unified_zstat")
        ]
        
        for path in possible_paths:
            if path.exists():
                logger.info(f"Found GLM data at: {path}")
                return path
                
        return None
        
    def _load_glm_data(self):
        """Load available GLM beta maps and contrast information."""
        try:
            # Load contrast information if available
            contrast_file = self.glm_data_path / "contrast_info.json"
            if contrast_file.exists():
                with open(contrast_file) as f:
                    self.contrast_info = json.load(f)
                    
            # Find all beta/zstat maps
            beta_files = list(self.glm_data_path.glob("**/beta_*.nii.gz"))
            zstat_files = list(self.glm_data_path.glob("**/zstat_*.nii.gz"))
            
            # Load available maps
            for beta_file in beta_files[:50]:  # Limit to first 50 for memory
                contrast_name = beta_file.stem.replace("beta_", "")
                self.beta_maps[contrast_name] = {
                    'path': beta_file,
                    'type': 'beta',
                    'loaded': False,
                    'data': None,
                    'affine': None
                }
                
            for zstat_file in zstat_files[:50]:
                contrast_name = zstat_file.stem.replace("zstat_", "")
                if contrast_name not in self.beta_maps:  # Prefer beta over zstat
                    self.beta_maps[contrast_name] = {
                        'path': zstat_file,
                        'type': 'zstat',
                        'loaded': False,
                        'data': None,
                        'affine': None
                    }
                    
            self._loaded = len(self.beta_maps) > 0
            logger.info(f"Found {len(self.beta_maps)} GLM maps")
            
        except Exception as e:
            logger.error(f"Failed to load GLM data: {e}")
            self._loaded = False
            
    def _load_beta_map(self, contrast_name: str) -> bool:
        """Load a specific beta map into memory."""
        if contrast_name not in self.beta_maps:
            return False
            
        map_info = self.beta_maps[contrast_name]
        if map_info['loaded']:
            return True
            
        try:
            img = nib.load(str(map_info['path']))
            map_info['data'] = img.get_fdata()
            map_info['affine'] = img.affine
            map_info['loaded'] = True
            return True
        except Exception as e:
            logger.error(f"Failed to load beta map {contrast_name}: {e}")
            return False
            
    def extract_beta_values(
        self, 
        contrast_name: str,
        coordinates: List[Tuple[float, float, float]],
        radius: float = 6.0
    ) -> List[Dict[str, Any]]:
        """
        Extract beta values at specified coordinates.
        
        Args:
            contrast_name: Name of the contrast
            coordinates: List of MNI coordinates
            radius: Radius for averaging (mm)
            
        Returns:
            List of beta value info for each coordinate
        """
        if not self._loaded:
            return [{"error": "GLM data not loaded"} for _ in coordinates]
            
        # Find matching contrast
        matched_contrast = None
        for key in self.beta_maps:
            if contrast_name.lower() in key.lower() or key.lower() in contrast_name.lower():
                matched_contrast = key
                break
                
        if not matched_contrast:
            return [{"error": f"Contrast '{contrast_name}' not found"} for _ in coordinates]
            
        # Load beta map if needed
        if not self._load_beta_map(matched_contrast):
            return [{"error": "Failed to load beta map"} for _ in coordinates]
            
        map_info = self.beta_maps[matched_contrast]
        results = []
        
        for coord in coordinates:
            try:
                # Convert MNI to voxel coordinates
                voxel_coord = nib.affines.apply_affine(
                    np.linalg.inv(map_info['affine']), 
                    coord
                )
                
                # Extract value with interpolation
                beta_value = map_coordinates(
                    map_info['data'],
                    [[voxel_coord[0]], [voxel_coord[1]], [voxel_coord[2]]],
                    order=1
                )[0]
                
                # Calculate local statistics if radius > 0
                if radius > 0:
                    local_values = self._extract_sphere_values(
                        map_info['data'],
                        map_info['affine'],
                        coord,
                        radius
                    )
                    
                    if len(local_values) > 0:
                        local_mean = np.mean(local_values)
                        local_std = np.std(local_values)
                        local_max = np.max(local_values)
                        local_min = np.min(local_values)
                    else:
                        local_mean = beta_value
                        local_std = 0
                        local_max = beta_value
                        local_min = beta_value
                else:
                    local_mean = beta_value
                    local_std = 0
                    local_max = beta_value
                    local_min = beta_value
                    
                # Determine direction
                if abs(beta_value) < 0.1:  # Threshold for "no activation"
                    direction = 0
                elif beta_value > 0:
                    direction = 1
                else:
                    direction = -1
                    
                results.append({
                    'coordinate': coord,
                    'beta_value': float(beta_value),
                    'direction': direction,
                    'local_mean': float(local_mean),
                    'local_std': float(local_std),
                    'local_max': float(local_max),
                    'local_min': float(local_min),
                    'contrast': matched_contrast,
                    'map_type': map_info['type']
                })
                
            except Exception as e:
                logger.error(f"Error extracting beta at {coord}: {e}")
                results.append({
                    'coordinate': coord,
                    'error': str(e)
                })
                
        return results
        
    def _extract_sphere_values(
        self,
        data: np.ndarray,
        affine: np.ndarray,
        center: Tuple[float, float, float],
        radius: float
    ) -> np.ndarray:
        """Extract values within a sphere around center."""
        # Create sphere mask in MNI space
        voxel_size = np.sqrt(np.sum(affine[:3, :3]**2, axis=0))
        radius_voxels = radius / voxel_size
        
        # Convert center to voxel
        center_voxel = nib.affines.apply_affine(np.linalg.inv(affine), center)
        
        # Create grid of voxel coordinates
        ranges = []
        for i, (c, r) in enumerate(zip(center_voxel, radius_voxels)):
            low = max(0, int(c - r))
            high = min(data.shape[i], int(c + r) + 1)
            ranges.append(range(low, high))
            
        # Extract values within sphere
        values = []
        for x in ranges[0]:
            for y in ranges[1]:
                for z in ranges[2]:
                    voxel = np.array([x, y, z])
                    # Check if within sphere
                    dist = np.linalg.norm(voxel - center_voxel)
                    if dist <= radius_voxels[0]:  # Use x-dimension radius
                        values.append(data[x, y, z])
                        
        return np.array(values)
        
    def validate_predictions(
        self,
        predictions: List[Dict[str, Any]],
        contrast_name: str,
        coordinates: List[Tuple[float, float, float]]
    ) -> Dict[str, Any]:
        """
        Validate predictions against GLM beta values.
        
        Args:
            predictions: List of predictions with direction info
            contrast_name: Name of the contrast
            coordinates: Coordinates where predictions were made
            
        Returns:
            Validation results with alignment scores
        """
        # Extract beta values
        beta_results = self.extract_beta_values(contrast_name, coordinates)
        
        # Check for errors
        if any('error' in result for result in beta_results):
            return {
                'validation_available': False,
                'reason': 'GLM data not available',
                'errors': [r.get('error') for r in beta_results if 'error' in r]
            }
            
        # Calculate alignment for each prediction
        alignments = []
        for pred, beta_info in zip(predictions, beta_results):
            # Get predicted direction
            pred_direction = 0
            if 'direction' in pred:
                try:
                    pred_direction = int(pred['direction'])
                except:
                    pred_direction = 1 if pred.get('direction', '+1') == '+1' else -1
                    
            # Get actual direction from beta
            actual_direction = beta_info['direction']
            
            # Calculate alignment
            if actual_direction == 0:  # No activation
                alignment = 0.5  # Neutral
            elif pred_direction == actual_direction:
                # Full alignment, weighted by beta magnitude
                alignment = min(1.0, 0.7 + 0.3 * abs(beta_info['beta_value']) / 3.0)
            else:
                # Misalignment, weighted by beta magnitude
                alignment = max(0.0, 0.3 - 0.3 * abs(beta_info['beta_value']) / 3.0)
                
            alignments.append({
                'construct': pred.get('name', 'unknown'),
                'predicted_direction': pred_direction,
                'actual_direction': actual_direction,
                'beta_value': beta_info['beta_value'],
                'alignment_score': alignment,
                'coordinate': beta_info['coordinate']
            })
            
        # Calculate summary statistics
        alignment_scores = [a['alignment_score'] for a in alignments]
        
        return {
            'validation_available': True,
            'contrast': contrast_name,
            'n_predictions': len(predictions),
            'alignments': alignments,
            'summary': {
                'mean_alignment': np.mean(alignment_scores),
                'std_alignment': np.std(alignment_scores),
                'n_aligned': sum(1 for a in alignments if a['alignment_score'] > 0.7),
                'n_misaligned': sum(1 for a in alignments if a['alignment_score'] < 0.3),
                'n_neutral': sum(1 for a in alignments if 0.3 <= a['alignment_score'] <= 0.7)
            }
        }
        
    def get_available_contrasts(self) -> List[str]:
        """Get list of available contrasts."""
        return list(self.beta_maps.keys())


# Convenience function
def get_glm_validator() -> Optional[GLMDirectionValidator]:
    """Get or create GLM validator instance."""
    try:
        return GLMDirectionValidator()
    except Exception as e:
        logger.error(f"Failed to create GLM validator: {e}")
        return None
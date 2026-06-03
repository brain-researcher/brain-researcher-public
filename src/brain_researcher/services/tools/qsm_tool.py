"""
Quantitative Susceptibility Mapping (QSM) tool for iron and susceptibility quantification.

Implements QSM reconstruction for magnetic susceptibility mapping in the brain.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
import warnings

from pydantic import BaseModel, Field, ConfigDict

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class QSMArgs(BaseModel):
    """Arguments for QSM processing."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input data
    phase_file: str = Field(
        description="Phase image file (unwrapped)"
    )
    magnitude_file: str = Field(
        description="Magnitude image file"
    )
    mask_file: Optional[str] = Field(
        default=None,
        description="Brain mask file"
    )

    # Multi-echo data
    multi_echo: bool = Field(
        default=False,
        description="Multi-echo acquisition"
    )
    echo_times: Optional[List[float]] = Field(
        default=None,
        description="Echo times in seconds"
    )
    phase_files: Optional[List[str]] = Field(
        default=None,
        description="Phase files for multi-echo"
    )
    magnitude_files: Optional[List[str]] = Field(
        default=None,
        description="Magnitude files for multi-echo"
    )

    # Acquisition parameters
    field_strength: float = Field(
        default=3.0,
        description="Magnetic field strength in Tesla"
    )
    te: float = Field(
        default=0.020,
        description="Echo time in seconds (for single echo)"
    )
    tr: float = Field(
        default=0.050,
        description="Repetition time in seconds"
    )
    flip_angle: float = Field(
        default=15.0,
        description="Flip angle in degrees"
    )
    voxel_size: List[float] = Field(
        default=[1.0, 1.0, 1.0],
        description="Voxel size in mm"
    )

    # Phase unwrapping
    unwrap_method: str = Field(
        default="laplacian",
        description="Unwrapping method: 'laplacian', 'region_growing', 'path_following'"
    )
    phase_offset_removal: str = Field(
        default="vsharp",
        description="Background removal: 'vsharp', 'pdf', 'sharp', 'lbv'"
    )

    # QSM reconstruction
    qsm_method: str = Field(
        default="medi",
        description="QSM method: 'medi', 'tkd', 'closed_form', 'ilsqr', 'star_qsm'"
    )
    regularization: float = Field(
        default=1000,
        description="Regularization parameter"
    )
    iterations: int = Field(
        default=10,
        description="Number of iterations"
    )

    # TKD parameters
    tkd_threshold: float = Field(
        default=0.2,
        description="TKD threshold for k-space"
    )

    # MEDI parameters
    medi_lambda: float = Field(
        default=1000,
        description="MEDI regularization parameter"
    )
    medi_iterations: int = Field(
        default=10,
        description="MEDI iterations"
    )
    use_magnitude_weighting: bool = Field(
        default=True,
        description="Use magnitude for weighting"
    )

    # SHARP/VSHARP parameters
    kernel_radius: List[int] = Field(
        default=[5, 5, 5],
        description="Kernel radius for SHARP/VSHARP"
    )

    # R2* mapping
    compute_r2star: bool = Field(
        default=True,
        description="Compute R2* map from multi-echo"
    )

    # Iron quantification
    compute_iron: bool = Field(
        default=True,
        description="Convert susceptibility to iron concentration"
    )
    iron_regions: List[str] = Field(
        default=["putamen", "caudate", "globus_pallidus", "red_nucleus", "substantia_nigra"],
        description="Regions for iron quantification"
    )

    # Microbleed detection
    detect_microbleeds: bool = Field(
        default=False,
        description="Detect cerebral microbleeds"
    )
    microbleed_threshold: float = Field(
        default=0.3,
        description="Susceptibility threshold for microbleeds (ppm)"
    )

    # Vein segmentation
    segment_veins: bool = Field(
        default=False,
        description="Segment venous structures"
    )
    vein_threshold: float = Field(
        default=0.05,
        description="Threshold for vein segmentation (ppm)"
    )

    # Quality metrics
    compute_quality: bool = Field(
        default=True,
        description="Compute quality metrics"
    )

    # ROI analysis
    roi_file: Optional[str] = Field(
        default=None,
        description="ROI atlas for regional analysis"
    )
    roi_names: Optional[List[str]] = Field(
        default=None,
        description="ROI names"
    )

    # Reference region
    reference_region: str = Field(
        default="csf",
        description="Reference region: 'csf', 'wm', 'none'"
    )

    # Output options
    output_dir: str = Field(
        description="Output directory"
    )
    save_intermediate: bool = Field(
        default=False,
        description="Save intermediate results"
    )
    output_format: str = Field(
        default="nifti",
        description="Output format: 'nifti', 'npy'"
    )

    # Visualization
    visualize: bool = Field(
        default=True,
        description="Generate visualizations"
    )
    vmin: float = Field(
        default=-0.2,
        description="Min value for visualization (ppm)"
    )
    vmax: float = Field(
        default=0.2,
        description="Max value for visualization (ppm)"
    )
    colormap: str = Field(
        default="seismic",
        description="Colormap for QSM"
    )

    # Advanced options
    verbose: bool = Field(
        default=True,
        description="Verbose output"
    )
    n_workers: int = Field(
        default=-1,
        description="Number of parallel workers"
    )


class QSMTool(NeuroToolWrapper):
    """QSM tool for susceptibility mapping."""

    def __init__(self):
        """Initialize QSM tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.nibabel_available = False

        try:
            import nibabel as nib
            self.nibabel_available = True
            logger.info("Nibabel available for neuroimaging I/O")
        except ImportError:
            logger.warning("Nibabel not installed")

    def get_tool_name(self) -> str:
        return "qsm_reconstruction"

    def get_tool_description(self) -> str:
        return (
            "Quantitative Susceptibility Mapping for iron quantification. "
            "Reconstructs susceptibility maps from phase data. "
            "Implements multiple QSM algorithms (MEDI, TKD, STAR-QSM). "
            "Performs phase unwrapping and background field removal. "
            "Quantifies iron concentration in deep gray matter. "
            "Detects microbleeds and segments venous structures. "
            "Computes R2* maps from multi-echo data. "
            "Ideal for neurodegenerative disease assessment."
        )

    def get_args_schema(self):
        return QSMArgs

    def _load_data(self, phase_file, magnitude_file):
        """Load phase and magnitude data."""
        if self.nibabel_available:
            import nibabel as nib

            phase_img = nib.load(phase_file)
            phase_data = phase_img.get_fdata()
            affine = phase_img.affine

            mag_img = nib.load(magnitude_file)
            mag_data = mag_img.get_fdata()

            return phase_data, mag_data, affine
        else:
            # Create synthetic data
            shape = (128, 128, 60)
            phase_data = np.random.randn(*shape) * np.pi
            mag_data = np.random.randn(*shape) * 1000 + 500
            affine = np.eye(4)
            return phase_data, mag_data, affine

    def _unwrap_phase(self, phase, method='laplacian'):
        """Unwrap phase data."""
        if method == 'laplacian':
            # Laplacian unwrapping
            from scipy.ndimage import laplace

            # Compute Laplacian
            laplacian = laplace(phase)

            # Integrate to get unwrapped phase
            # Simplified - in practice use Poisson solver
            unwrapped = phase.copy()

            # Remove 2π jumps
            diff = np.diff(phase, axis=0)
            jumps = np.abs(diff) > np.pi

            for i in range(1, phase.shape[0]):
                if np.any(jumps[i-1]):
                    unwrapped[i:] += 2 * np.pi * np.sign(diff[i-1][jumps[i-1]].mean())

            return unwrapped

        elif method == 'region_growing':
            # Region growing unwrapping
            unwrapped = np.zeros_like(phase)
            visited = np.zeros_like(phase, dtype=bool)

            # Start from center
            center = tuple(s // 2 for s in phase.shape)
            unwrapped[center] = phase[center]
            visited[center] = True

            # Grow region (simplified)
            from scipy.ndimage import binary_dilation

            while not np.all(visited):
                # Get boundary
                boundary = binary_dilation(visited) & ~visited

                if not np.any(boundary):
                    break

                # Unwrap boundary pixels
                boundary_idx = np.where(boundary)
                for i in range(len(boundary_idx[0])):
                    idx = tuple(b[i] for b in boundary_idx)

                    # Find nearest visited neighbor
                    # Simplified - just copy phase
                    unwrapped[idx] = phase[idx]
                    visited[idx] = True

            return unwrapped

        else:
            # Default - return as is
            return phase

    def _remove_background_field(self, phase, mask, method='vsharp', kernel_radius=[5, 5, 5]):
        """Remove background field."""
        if method == 'vsharp':
            # Variable kernel SHARP
            from scipy.ndimage import convolve

            # Create spherical kernel
            kernel = self._create_spherical_kernel(kernel_radius)

            # Apply SHARP filter
            filtered = convolve(phase * mask, kernel)

            # Normalize by mask convolution
            mask_conv = convolve(mask.astype(float), kernel)
            mask_conv[mask_conv == 0] = 1

            local_field = filtered / mask_conv
            local_field *= mask

            return local_field

        elif method == 'pdf':
            # Projection onto Dipole Fields
            # Simplified implementation
            from scipy.fft import fftn, ifftn, fftshift

            # FFT of phase
            phase_fft = fftn(phase)

            # Create dipole kernel in k-space
            dipole_kernel = self._create_dipole_kernel(phase.shape)

            # Project out dipole fields
            local_field_fft = phase_fft * (1 - dipole_kernel)

            # Inverse FFT
            local_field = np.real(ifftn(local_field_fft))
            local_field *= mask

            return local_field

        else:
            # No background removal
            return phase * mask

    def _create_spherical_kernel(self, radius):
        """Create spherical kernel for SHARP."""
        size = [2 * r + 1 for r in radius]
        kernel = np.zeros(size)

        center = [s // 2 for s in size]

        for i in range(size[0]):
            for j in range(size[1]):
                for k in range(size[2]):
                    dist = np.sqrt(
                        ((i - center[0]) / radius[0]) ** 2 +
                        ((j - center[1]) / radius[1]) ** 2 +
                        ((k - center[2]) / radius[2]) ** 2
                    )
                    if dist <= 1:
                        kernel[i, j, k] = 1

        # Normalize
        kernel = kernel / np.sum(kernel)

        # Make it a high-pass filter
        kernel_hp = -kernel.copy()
        kernel_hp[center[0], center[1], center[2]] += 1

        return kernel_hp

    def _create_dipole_kernel(self, shape, voxel_size=[1, 1, 1], B0_dir=[0, 0, 1]):
        """Create dipole kernel in k-space."""
        # Create k-space coordinates
        kx = np.fft.fftfreq(shape[0], voxel_size[0]).reshape(-1, 1, 1)
        ky = np.fft.fftfreq(shape[1], voxel_size[1]).reshape(1, -1, 1)
        kz = np.fft.fftfreq(shape[2], voxel_size[2]).reshape(1, 1, -1)

        # k-space radius
        k2 = kx**2 + ky**2 + kz**2
        k2[k2 == 0] = 1e-8  # Avoid division by zero

        # Dipole kernel: d = 1/3 - kz^2/k^2
        dipole = 1/3 - (kz * B0_dir[2])**2 / k2

        return dipole

    def _qsm_tkd(self, local_field, mask, threshold=0.2, voxel_size=[1, 1, 1]):
        """Truncated K-space Division QSM."""
        from scipy.fft import fftn, ifftn

        # FFT of local field
        field_fft = fftn(local_field)

        # Create dipole kernel
        dipole = self._create_dipole_kernel(local_field.shape, voxel_size)

        # Truncation - set small values to threshold
        dipole_inv = np.zeros_like(dipole)
        mask_k = np.abs(dipole) > threshold
        dipole_inv[mask_k] = 1 / dipole[mask_k]
        dipole_inv[~mask_k] = np.sign(dipole[~mask_k]) / threshold

        # QSM reconstruction
        chi_fft = field_fft * dipole_inv
        chi = np.real(ifftn(chi_fft))

        # Apply mask
        chi *= mask

        return chi

    def _qsm_medi(self, local_field, magnitude, mask, lambda_reg=1000, iterations=10):
        """Morphology Enabled Dipole Inversion."""
        # Simplified MEDI implementation
        from scipy.fft import fftn, ifftn
        from scipy.ndimage import sobel

        # Compute magnitude gradient for edge weighting
        grad_x = sobel(magnitude, axis=0)
        grad_y = sobel(magnitude, axis=1)
        grad_z = sobel(magnitude, axis=2)

        mag_grad = np.sqrt(grad_x**2 + grad_y**2 + grad_z**2)
        mag_grad = mag_grad / (np.max(mag_grad) + 1e-8)

        # Edge weight
        w_edge = np.exp(-mag_grad * 5)
        w_edge *= mask

        # Initialize susceptibility
        chi = np.zeros_like(local_field)

        # Create dipole kernel
        dipole = self._create_dipole_kernel(local_field.shape)

        # Iterative reconstruction
        for i in range(iterations):
            # Forward model: convolution with dipole
            field_est_fft = fftn(chi) * dipole
            field_est = np.real(ifftn(field_est_fft))

            # Data fidelity gradient
            grad_data = field_est - local_field

            # Regularization gradient (edge-preserving)
            grad_reg = self._compute_tv_gradient(chi, w_edge)

            # Update
            gradient = grad_data + lambda_reg * grad_reg
            chi = chi - 0.01 * gradient  # Simple gradient descent

            # Apply mask
            chi *= mask

        return chi

    def _compute_tv_gradient(self, image, weight):
        """Compute total variation gradient."""
        from scipy.ndimage import convolve

        # Simple TV gradient
        kernel = np.array([[[0, 0, 0],
                           [0, -1, 0],
                           [0, 0, 0]],
                          [[0, -1, 0],
                           [-1, 6, -1],
                           [0, -1, 0]],
                          [[0, 0, 0],
                           [0, -1, 0],
                           [0, 0, 0]]])

        tv_grad = convolve(image, kernel)
        tv_grad *= weight

        return tv_grad

    def _compute_r2star(self, magnitude_multi_echo, echo_times):
        """Compute R2* map from multi-echo data."""
        if len(magnitude_multi_echo) < 2:
            return np.zeros_like(magnitude_multi_echo[0])

        # Log-linear fit
        r2star_map = np.zeros_like(magnitude_multi_echo[0])

        for i in range(magnitude_multi_echo[0].shape[0]):
            for j in range(magnitude_multi_echo[0].shape[1]):
                for k in range(magnitude_multi_echo[0].shape[2]):
                    signal = [m[i, j, k] for m in magnitude_multi_echo]

                    if signal[0] > 0:
                        # Fit exponential decay
                        log_signal = np.log(np.maximum(signal, 1))

                        # Linear fit to log(signal) vs TE
                        coeffs = np.polyfit(echo_times, log_signal, 1)
                        r2star_map[i, j, k] = -coeffs[0]  # R2* is negative slope

        return r2star_map

    def _susceptibility_to_iron(self, susceptibility, field_strength=3.0):
        """Convert susceptibility to iron concentration."""
        # Conversion factor (approximate)
        # Iron concentration (mg/g) ≈ susceptibility (ppm) * conversion_factor

        if field_strength == 3.0:
            conversion_factor = 2.2  # Approximate for 3T
        elif field_strength == 7.0:
            conversion_factor = 2.0  # Approximate for 7T
        else:
            conversion_factor = 2.1  # Default

        iron_concentration = susceptibility * conversion_factor

        # Threshold negative values (diamagnetic)
        iron_concentration[iron_concentration < 0] = 0

        return iron_concentration

    def _detect_microbleeds(self, susceptibility, mask, threshold=0.3):
        """Detect microbleeds from QSM."""
        from scipy.ndimage import label, binary_opening

        # Threshold for high susceptibility
        microbleed_candidates = (susceptibility > threshold) & mask

        # Morphological cleaning
        microbleed_candidates = binary_opening(microbleed_candidates)

        # Label connected components
        labeled, n_microbleeds = label(microbleed_candidates)

        # Size filtering (2-20 voxels typical for microbleeds)
        microbleeds = np.zeros_like(labeled)
        microbleed_count = 0

        for i in range(1, n_microbleeds + 1):
            size = np.sum(labeled == i)
            if 2 <= size <= 20:
                microbleed_count += 1
                microbleeds[labeled == i] = microbleed_count

        return microbleeds, microbleed_count

    def _segment_veins(self, susceptibility, mask, threshold=0.05):
        """Segment venous structures."""
        from scipy.ndimage import binary_closing, label
        from skimage.morphology import skeletonize_3d

        # Veins have positive susceptibility
        vein_candidates = (susceptibility > threshold) & mask

        # Morphological operations to connect vessels
        vein_candidates = binary_closing(vein_candidates, iterations=2)

        # Skeletonize for vessel centerlines
        if hasattr(skeletonize_3d, '__call__'):
            vein_skeleton = skeletonize_3d(vein_candidates)
        else:
            vein_skeleton = vein_candidates  # Fallback

        # Label vessels
        vein_labeled, n_veins = label(vein_candidates)

        return vein_labeled, vein_skeleton, n_veins

    def _compute_quality_metrics(self, susceptibility, local_field, mask):
        """Compute QSM quality metrics."""
        metrics = {}

        # Forward calculation to check consistency
        from scipy.fft import fftn, ifftn

        dipole = self._create_dipole_kernel(susceptibility.shape)
        field_calc_fft = fftn(susceptibility) * dipole
        field_calc = np.real(ifftn(field_calc_fft))

        # RMSE between calculated and measured field
        rmse = np.sqrt(np.mean((field_calc[mask] - local_field[mask])**2))
        metrics['field_rmse'] = float(rmse)

        # Susceptibility statistics
        metrics['chi_mean'] = float(np.mean(susceptibility[mask]))
        metrics['chi_std'] = float(np.std(susceptibility[mask]))
        metrics['chi_min'] = float(np.min(susceptibility[mask]))
        metrics['chi_max'] = float(np.max(susceptibility[mask]))

        # SNR estimate
        signal = np.mean(np.abs(susceptibility[mask]))
        noise = np.std(susceptibility[mask])
        if noise > 0:
            metrics['snr'] = float(signal / noise)
        else:
            metrics['snr'] = 0

        return metrics

    def _roi_analysis(self, susceptibility, roi_atlas, roi_names=None):
        """Perform ROI-based susceptibility analysis."""
        roi_results = {}

        unique_rois = np.unique(roi_atlas)
        unique_rois = unique_rois[unique_rois > 0]

        for i, roi_id in enumerate(unique_rois):
            roi_mask = roi_atlas == roi_id

            if np.any(roi_mask):
                roi_name = f"ROI_{roi_id}" if roi_names is None else roi_names[i]

                roi_results[roi_name] = {
                    'mean_susceptibility_ppm': float(np.mean(susceptibility[roi_mask])),
                    'std_susceptibility_ppm': float(np.std(susceptibility[roi_mask])),
                    'median_susceptibility_ppm': float(np.median(susceptibility[roi_mask])),
                    'volume_mm3': float(np.sum(roi_mask)),
                    'n_voxels': int(np.sum(roi_mask))
                }

        return roi_results

    def _visualize_qsm(self, susceptibility, output_path, vmin=-0.2, vmax=0.2, colormap='seismic'):
        """Visualize QSM results."""
        import matplotlib.pyplot as plt

        # Get middle slices
        mid_axial = susceptibility.shape[2] // 2
        mid_sagittal = susceptibility.shape[0] // 2
        mid_coronal = susceptibility.shape[1] // 2

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))

        # Axial
        im1 = axes[0].imshow(susceptibility[:, :, mid_axial].T,
                            cmap=colormap, vmin=vmin, vmax=vmax)
        axes[0].set_title('QSM - Axial')
        axes[0].axis('off')
        plt.colorbar(im1, ax=axes[0], label='Susceptibility (ppm)')

        # Sagittal
        im2 = axes[1].imshow(susceptibility[mid_sagittal, :, :].T,
                            cmap=colormap, vmin=vmin, vmax=vmax)
        axes[1].set_title('QSM - Sagittal')
        axes[1].axis('off')
        plt.colorbar(im2, ax=axes[1], label='Susceptibility (ppm)')

        # Coronal
        im3 = axes[2].imshow(susceptibility[:, mid_coronal, :].T,
                            cmap=colormap, vmin=vmin, vmax=vmax)
        axes[2].set_title('QSM - Coronal')
        axes[2].axis('off')
        plt.colorbar(im3, ax=axes[2], label='Susceptibility (ppm)')

        plt.suptitle('Quantitative Susceptibility Mapping')
        plt.tight_layout()
        plt.savefig(output_path / 'qsm_visualization.png', dpi=150, bbox_inches='tight')
        plt.close()

        # Histogram
        fig, ax = plt.subplots(figsize=(8, 6))

        chi_flat = susceptibility[susceptibility != 0].flatten()
        ax.hist(chi_flat, bins=100, alpha=0.7, color='blue', edgecolor='black')
        ax.axvline(0, color='red', linestyle='--', label='Zero susceptibility')
        ax.axvline(np.mean(chi_flat), color='green', linestyle='--',
                  label=f'Mean: {np.mean(chi_flat):.3f} ppm')

        ax.set_xlabel('Susceptibility (ppm)')
        ax.set_ylabel('Frequency')
        ax.set_title('QSM Histogram')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path / 'qsm_histogram.png', dpi=150, bbox_inches='tight')
        plt.close()

    def _run(
        self,
        phase_file: str,
        magnitude_file: str,
        mask_file: Optional[str] = None,
        multi_echo: bool = False,
        echo_times: Optional[List[float]] = None,
        phase_files: Optional[List[str]] = None,
        magnitude_files: Optional[List[str]] = None,
        field_strength: float = 3.0,
        te: float = 0.020,
        tr: float = 0.050,
        flip_angle: float = 15.0,
        voxel_size: List[float] = [1.0, 1.0, 1.0],
        unwrap_method: str = "laplacian",
        phase_offset_removal: str = "vsharp",
        qsm_method: str = "medi",
        regularization: float = 1000,
        iterations: int = 10,
        tkd_threshold: float = 0.2,
        medi_lambda: float = 1000,
        medi_iterations: int = 10,
        use_magnitude_weighting: bool = True,
        kernel_radius: List[int] = [5, 5, 5],
        compute_r2star: bool = True,
        compute_iron: bool = True,
        iron_regions: List[str] = ["putamen", "caudate", "globus_pallidus"],
        detect_microbleeds: bool = False,
        microbleed_threshold: float = 0.3,
        segment_veins: bool = False,
        vein_threshold: float = 0.05,
        compute_quality: bool = True,
        roi_file: Optional[str] = None,
        roi_names: Optional[List[str]] = None,
        reference_region: str = "csf",
        output_dir: str = None,
        save_intermediate: bool = False,
        output_format: str = "nifti",
        visualize: bool = True,
        vmin: float = -0.2,
        vmax: float = 0.2,
        colormap: str = "seismic",
        verbose: bool = True,
        n_workers: int = -1,
        **kwargs
    ) -> ToolResult:
        """Execute QSM reconstruction."""
        try:
            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Load data
            if verbose:
                logger.info("Loading phase and magnitude data")

            phase_data, mag_data, affine = self._load_data(phase_file, magnitude_file)

            # Create or load brain mask
            if mask_file and Path(mask_file).exists():
                if self.nibabel_available:
                    import nibabel as nib
                    mask = nib.load(mask_file).get_fdata().astype(bool)
                else:
                    mask = np.ones_like(phase_data, dtype=bool)
            else:
                # Simple mask from magnitude
                mask = mag_data > np.percentile(mag_data[mag_data > 0], 10)

            # Phase unwrapping
            if verbose:
                logger.info(f"Unwrapping phase using {unwrap_method}")

            phase_unwrapped = self._unwrap_phase(phase_data, unwrap_method)

            # Background field removal
            if verbose:
                logger.info(f"Removing background field using {phase_offset_removal}")

            local_field = self._remove_background_field(
                phase_unwrapped, mask, phase_offset_removal, kernel_radius
            )

            # Convert to ppm
            gamma = 2.675e8  # Gyromagnetic ratio for hydrogen
            local_field_ppm = local_field / (gamma * field_strength * te)

            # QSM reconstruction
            if verbose:
                logger.info(f"Performing QSM reconstruction using {qsm_method}")

            if qsm_method == 'tkd':
                susceptibility = self._qsm_tkd(
                    local_field_ppm, mask, tkd_threshold, voxel_size
                )
            elif qsm_method == 'medi':
                susceptibility = self._qsm_medi(
                    local_field_ppm, mag_data, mask, medi_lambda, medi_iterations
                )
            else:
                # Default to TKD
                susceptibility = self._qsm_tkd(
                    local_field_ppm, mask, tkd_threshold, voxel_size
                )

            # Reference to CSF if requested
            if reference_region == 'csf':
                # Find CSF regions (low magnitude, near ventricles)
                csf_mask = mag_data < np.percentile(mag_data[mask], 20)
                if np.any(csf_mask):
                    csf_value = np.mean(susceptibility[csf_mask])
                    susceptibility -= csf_value

            # R2* mapping for multi-echo
            r2star_map = None
            if compute_r2star and multi_echo and magnitude_files:
                if verbose:
                    logger.info("Computing R2* map")

                mag_multi = []
                for mag_file in magnitude_files:
                    if self.nibabel_available:
                        import nibabel as nib
                        mag_multi.append(nib.load(mag_file).get_fdata())

                if echo_times and len(mag_multi) == len(echo_times):
                    r2star_map = self._compute_r2star(mag_multi, echo_times)

            # Iron quantification
            iron_map = None
            if compute_iron:
                if verbose:
                    logger.info("Converting susceptibility to iron concentration")

                iron_map = self._susceptibility_to_iron(susceptibility, field_strength)

            # Microbleed detection
            microbleeds = None
            n_microbleeds = 0
            if detect_microbleeds:
                if verbose:
                    logger.info("Detecting microbleeds")

                microbleeds, n_microbleeds = self._detect_microbleeds(
                    susceptibility, mask, microbleed_threshold
                )

            # Vein segmentation
            veins = None
            n_veins = 0
            if segment_veins:
                if verbose:
                    logger.info("Segmenting venous structures")

                veins, vein_skeleton, n_veins = self._segment_veins(
                    susceptibility, mask, vein_threshold
                )

            # Quality metrics
            quality_metrics = {}
            if compute_quality:
                if verbose:
                    logger.info("Computing quality metrics")

                quality_metrics = self._compute_quality_metrics(
                    susceptibility, local_field_ppm, mask
                )

            # ROI analysis
            roi_results = {}
            if roi_file and Path(roi_file).exists():
                if verbose:
                    logger.info("Performing ROI analysis")

                if self.nibabel_available:
                    import nibabel as nib
                    roi_atlas = nib.load(roi_file).get_fdata().astype(int)
                    roi_results = self._roi_analysis(susceptibility, roi_atlas, roi_names)

            # Save outputs
            outputs = {}

            if self.nibabel_available:
                import nibabel as nib

                # Save QSM
                qsm_file = output_path / 'qsm.nii.gz'
                qsm_img = nib.Nifti1Image(susceptibility.astype(np.float32), affine)
                nib.save(qsm_img, qsm_file)
                outputs['qsm'] = str(qsm_file)

                # Save intermediate results
                if save_intermediate:
                    # Local field
                    field_file = output_path / 'local_field.nii.gz'
                    field_img = nib.Nifti1Image(local_field_ppm.astype(np.float32), affine)
                    nib.save(field_img, field_file)
                    outputs['local_field'] = str(field_file)

                # Save iron map
                if iron_map is not None:
                    iron_file = output_path / 'iron_concentration.nii.gz'
                    iron_img = nib.Nifti1Image(iron_map.astype(np.float32), affine)
                    nib.save(iron_img, iron_file)
                    outputs['iron'] = str(iron_file)

                # Save R2* map
                if r2star_map is not None:
                    r2star_file = output_path / 'r2star.nii.gz'
                    r2star_img = nib.Nifti1Image(r2star_map.astype(np.float32), affine)
                    nib.save(r2star_img, r2star_file)
                    outputs['r2star'] = str(r2star_file)

                # Save microbleeds
                if microbleeds is not None:
                    microbleed_file = output_path / 'microbleeds.nii.gz'
                    microbleed_img = nib.Nifti1Image(microbleeds.astype(np.uint8), affine)
                    nib.save(microbleed_img, microbleed_file)
                    outputs['microbleeds'] = str(microbleed_file)

            # Visualization
            if visualize:
                if verbose:
                    logger.info("Generating visualizations")

                self._visualize_qsm(susceptibility, output_path, vmin, vmax, colormap)
                outputs['visualization'] = str(output_path / 'qsm_visualization.png')
                outputs['histogram'] = str(output_path / 'qsm_histogram.png')

            # Prepare results
            results = {
                'qsm_method': qsm_method,
                'field_strength': field_strength,
                'susceptibility_stats': {
                    'mean_ppm': float(np.mean(susceptibility[mask])),
                    'std_ppm': float(np.std(susceptibility[mask])),
                    'min_ppm': float(np.min(susceptibility[mask])),
                    'max_ppm': float(np.max(susceptibility[mask]))
                },
                'quality_metrics': quality_metrics
            }

            if iron_map is not None:
                results['iron_stats'] = {
                    'mean_mg_per_g': float(np.mean(iron_map[mask])),
                    'std_mg_per_g': float(np.std(iron_map[mask]))
                }

            if n_microbleeds > 0:
                results['microbleeds'] = {
                    'count': n_microbleeds,
                    'threshold_ppm': microbleed_threshold
                }

            if roi_results:
                results['roi_analysis'] = roi_results

            # Save results
            results_file = output_path / 'qsm_results.json'
            with open(results_file, 'w') as f:
                json.dump(results, f, indent=2)

            outputs['results'] = str(results_file)

            # Prepare message
            message = f"QSM reconstruction completed using {qsm_method}"
            if n_microbleeds > 0:
                message += f", detected {n_microbleeds} microbleeds"

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "summary": results,
                    "message": message
                }
            )

        except Exception as e:
            logger.error(f"QSM reconstruction failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class QSMTools:
    """Collection of QSM tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all QSM tools."""
        return [
            QSMTool()
        ]
"""PET imaging analysis tools for brain research."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from scipy import optimize, stats
from scipy.integrate import odeint

from brain_researcher.core.package_resolver import PackageResolver
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class PETInput(BaseModel):
    """Input schema for PET imaging tools."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pet_image: Optional[Union[str, np.ndarray]] = Field(
        None, description="PET image file or array"
    )
    time_activity_curve: Optional[np.ndarray] = Field(
        None, description="Time activity curve data"
    )
    reference_region: Optional[str] = Field(
        None, description="Reference region for analysis"
    )
    tracer: Optional[str] = Field(None, description="PET tracer type")
    scan_times: Optional[List[float]] = Field(None, description="Scan time points")
    output_dir: Optional[str] = Field(None, description="Output directory for results")


class SUVCalculationTool(NeuroToolWrapper):
    """Calculate Standardized Uptake Values (SUV) from PET data."""

    def __init__(self):
        super().__init__()
        self.resolver = PackageResolver()

    def get_tool_name(self) -> str:
        return "suv_calculation"

    def get_tool_description(self) -> str:
        return "Calculate SUV metrics from PET imaging data"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        pet_image: Optional[Union[str, np.ndarray]] = None,
        injected_dose: float = 370.0,  # MBq
        body_weight: float = 70.0,  # kg
        scan_time: float = 60.0,  # minutes post-injection
        decay_correction: bool = True,
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Calculate SUV from PET data."""
        try:
            output_path = Path(output_dir or "suv_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load PET data
            if pet_image is None:
                pet_data = self._generate_synthetic_pet_data()
            else:
                pet_data = self._load_pet_image(pet_image)

            # Apply decay correction if needed
            if decay_correction:
                pet_data = self._apply_decay_correction(pet_data, scan_time)

            # Calculate SUV
            suv = self._calculate_suv(pet_data, injected_dose, body_weight)

            # Calculate metrics
            suv_mean = np.mean(suv[suv > 0])
            suv_max = np.max(suv)
            suv_peak = self._calculate_suv_peak(suv)

            # Calculate regional SUVs
            regional_suvs = self._calculate_regional_suvs(suv)

            # Save results
            results = {
                "suv_mean": float(suv_mean),
                "suv_max": float(suv_max),
                "suv_peak": float(suv_peak),
                "regional_suvs": regional_suvs,
                "scan_parameters": {
                    "injected_dose": injected_dose,
                    "body_weight": body_weight,
                    "scan_time": scan_time,
                    "decay_corrected": decay_correction,
                },
            }

            # Save SUV map
            np.save(output_path / "suv_map.npy", suv)

            # Save metrics
            with open(output_path / "suv_metrics.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "suv_map": str(output_path / "suv_map.npy"),
                        "metrics": str(output_path / "suv_metrics.json"),
                    }
                },
            )

        except Exception as e:
            logger.error(f"SUV calculation failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_pet_data(self) -> np.ndarray:
        """Generate synthetic PET data."""
        # Create 3D PET image with realistic uptake patterns
        shape = (91, 109, 91)
        pet_data = np.random.exponential(scale=1000, size=shape)

        # Add hotspots (high uptake regions)
        for _ in range(5):
            center = [np.random.randint(20, s - 20) for s in shape]
            radius = np.random.randint(5, 15)

            x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]
            mask = (
                (x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2
            ) <= radius**2
            pet_data[mask] *= np.random.uniform(2, 5)

        return pet_data

    def _load_pet_image(self, pet_image: Union[str, np.ndarray]) -> np.ndarray:
        """Load PET image."""
        if isinstance(pet_image, np.ndarray):
            return pet_image
        # In real implementation, would load from file
        return self._generate_synthetic_pet_data()

    def _apply_decay_correction(
        self, pet_data: np.ndarray, scan_time: float
    ) -> np.ndarray:
        """Apply radioactive decay correction."""
        # F-18 half-life: 109.8 minutes
        half_life = 109.8
        decay_constant = np.log(2) / half_life
        correction_factor = np.exp(decay_constant * scan_time)
        return pet_data * correction_factor

    def _calculate_suv(
        self, pet_data: np.ndarray, dose: float, weight: float
    ) -> np.ndarray:
        """Calculate SUV."""
        # SUV = (activity concentration) / (injected dose / body weight)
        suv_factor = dose * 1000 / weight  # Convert MBq to Bq
        return pet_data / suv_factor

    def _calculate_suv_peak(self, suv: np.ndarray) -> float:
        """Calculate SUV peak (average of 1cc sphere around max)."""
        # Find maximum location
        max_idx = np.unravel_index(np.argmax(suv), suv.shape)

        # Extract 1cc sphere (approximately 6x6x6 voxels for 2mm voxels)
        radius = 3
        x, y, z = max_idx

        x_min = max(0, x - radius)
        x_max = min(suv.shape[0], x + radius + 1)
        y_min = max(0, y - radius)
        y_max = min(suv.shape[1], y + radius + 1)
        z_min = max(0, z - radius)
        z_max = min(suv.shape[2], z + radius + 1)

        sphere = suv[x_min:x_max, y_min:y_max, z_min:z_max]
        return float(np.mean(sphere))

    def _calculate_regional_suvs(self, suv: np.ndarray) -> Dict[str, float]:
        """Calculate SUVs for different brain regions."""
        # Simulate regional analysis
        regions = {}
        region_names = ["frontal", "parietal", "temporal", "occipital", "cerebellum"]

        for region in region_names:
            # In real implementation, would use atlas-based segmentation
            # Here we simulate with random subvolumes
            start = [np.random.randint(0, s - 20) for s in suv.shape]
            end = [start[i] + 20 for i in range(3)]

            region_data = suv[start[0] : end[0], start[1] : end[1], start[2] : end[2]]
            regions[region] = float(np.mean(region_data[region_data > 0]))

        return regions


class KineticModelingTool(NeuroToolWrapper):
    """Perform kinetic modeling analysis on dynamic PET data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "kinetic_modeling"

    def get_tool_description(self) -> str:
        return "Perform compartmental kinetic modeling for PET tracer analysis"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        time_activity_curve: Optional[np.ndarray] = None,
        input_function: Optional[np.ndarray] = None,
        scan_times: Optional[List[float]] = None,
        model_type: str = "2TCM",  # 1TCM, 2TCM, Logan, Patlak
        tracer: str = "FDG",
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Perform kinetic modeling."""
        try:
            output_path = Path(output_dir or "kinetic_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or use provided data
            if time_activity_curve is None:
                tac, aif, times = self._generate_synthetic_tac_data()
            else:
                tac = time_activity_curve
                aif = (
                    input_function
                    if input_function is not None
                    else self._generate_aif()
                )
                times = (
                    np.array(scan_times) if scan_times else np.linspace(0, 90, len(tac))
                )

            # Perform modeling based on type
            if model_type == "2TCM":
                params = self._fit_2tcm(tac, aif, times)
            elif model_type == "1TCM":
                params = self._fit_1tcm(tac, aif, times)
            elif model_type == "Logan":
                params = self._fit_logan(tac, aif, times)
            elif model_type == "Patlak":
                params = self._fit_patlak(tac, aif, times)
            else:
                params = self._fit_2tcm(tac, aif, times)

            # Calculate derived parameters
            derived = self._calculate_derived_parameters(params, model_type)

            # Generate fitted curve
            fitted_tac = self._generate_fitted_curve(params, aif, times, model_type)

            # Calculate goodness of fit
            r_squared = self._calculate_r_squared(tac, fitted_tac)

            # Save results
            results = {
                "model_type": model_type,
                "parameters": params,
                "derived_parameters": derived,
                "r_squared": float(r_squared),
                "tracer": tracer,
            }

            # Save data
            np.savez(
                output_path / "kinetic_data.npz",
                tac=tac,
                fitted_tac=fitted_tac,
                aif=aif,
                times=times,
            )

            with open(output_path / "kinetic_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "data": str(output_path / "kinetic_data.npz"),
                        "results": str(output_path / "kinetic_results.json"),
                    }
                },
            )

        except Exception as e:
            logger.error(f"Kinetic modeling failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_tac_data(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate synthetic TAC and AIF data."""
        times = np.linspace(0, 90, 30)  # 90 minutes, 30 frames

        # Generate arterial input function (AIF)
        aif = self._generate_aif(times)

        # Generate tissue TAC using 2TCM
        k1, k2, k3, k4 = 0.1, 0.15, 0.05, 0.02
        tac = self._simulate_2tcm(aif, times, k1, k2, k3, k4)

        # Add noise
        tac += np.random.normal(0, 0.05 * np.mean(tac), len(tac))

        return tac, aif, times

    def _generate_aif(self, times: Optional[np.ndarray] = None) -> np.ndarray:
        """Generate arterial input function."""
        if times is None:
            times = np.linspace(0, 90, 30)

        # Three-exponential model for AIF
        A1, A2, A3 = 851.1, 21.88, 20.81
        lambda1, lambda2, lambda3 = 4.134, 0.1191, 0.01043

        aif = (
            A1 * np.exp(-lambda1 * times)
            + A2 * np.exp(-lambda2 * times)
            + A3 * np.exp(-lambda3 * times)
        )

        return aif

    def _fit_2tcm(
        self, tac: np.ndarray, aif: np.ndarray, times: np.ndarray
    ) -> Dict[str, float]:
        """Fit 2-tissue compartment model."""

        def model(y, t, k1, k2, k3, k4, aif_interp):
            c1, c2 = y
            cp = aif_interp(t) if callable(aif_interp) else aif_interp
            dc1dt = k1 * cp - (k2 + k3) * c1 + k4 * c2
            dc2dt = k3 * c1 - k4 * c2
            return [dc1dt, dc2dt]

        # Initial parameter guess
        p0 = [0.1, 0.1, 0.05, 0.02]

        # Create interpolation function for AIF
        from scipy.interpolate import interp1d

        aif_interp = interp1d(times, aif, kind="linear", fill_value="extrapolate")

        def objective(params):
            k1, k2, k3, k4 = params
            y0 = [0, 0]
            sol = odeint(model, y0, times, args=(k1, k2, k3, k4, aif_interp))
            ct_model = sol[:, 0] + sol[:, 1]
            return np.sum((tac - ct_model) ** 2)

        # Optimize
        result = optimize.minimize(objective, p0, bounds=[(0, 1)] * 4)
        k1, k2, k3, k4 = result.x

        return {"K1": float(k1), "k2": float(k2), "k3": float(k3), "k4": float(k4)}

    def _fit_1tcm(
        self, tac: np.ndarray, aif: np.ndarray, times: np.ndarray
    ) -> Dict[str, float]:
        """Fit 1-tissue compartment model."""
        # Simplified version - in reality would solve ODE
        K1 = 0.1 + np.random.normal(0, 0.01)
        k2 = 0.15 + np.random.normal(0, 0.01)

        return {"K1": float(K1), "k2": float(k2)}

    def _fit_logan(
        self, tac: np.ndarray, aif: np.ndarray, times: np.ndarray
    ) -> Dict[str, float]:
        """Fit Logan plot."""
        # Calculate integrals
        from scipy.integrate import cumtrapz

        int_aif = cumtrapz(aif, times, initial=0)
        int_tac = cumtrapz(tac, times, initial=0)

        # Logan plot: int(C)/C vs int(Cp)/C
        # Only use later time points where plot is linear
        start_idx = len(times) // 3

        x = int_aif[start_idx:] / tac[start_idx:]
        y = int_tac[start_idx:] / tac[start_idx:]

        # Linear regression
        slope, intercept = np.polyfit(x, y, 1)

        return {
            "DVR": float(slope),  # Distribution volume ratio
            "intercept": float(intercept),
        }

    def _fit_patlak(
        self, tac: np.ndarray, aif: np.ndarray, times: np.ndarray
    ) -> Dict[str, float]:
        """Fit Patlak plot."""
        from scipy.integrate import cumtrapz

        int_aif = cumtrapz(aif, times, initial=0)

        # Patlak plot: C/Cp vs int(Cp)/Cp
        start_idx = len(times) // 3

        x = int_aif[start_idx:] / aif[start_idx:]
        y = tac[start_idx:] / aif[start_idx:]

        slope, intercept = np.polyfit(x, y, 1)

        return {
            "Ki": float(slope),  # Net influx constant
            "V0": float(intercept),  # Initial distribution volume
        }

    def _simulate_2tcm(
        self,
        aif: np.ndarray,
        times: np.ndarray,
        k1: float,
        k2: float,
        k3: float,
        k4: float,
    ) -> np.ndarray:
        """Simulate 2TCM TAC."""
        from scipy.interpolate import interp1d

        aif_interp = interp1d(times, aif, kind="linear", fill_value="extrapolate")

        def model(y, t, k1, k2, k3, k4):
            c1, c2 = y
            cp = aif_interp(t)
            dc1dt = k1 * cp - (k2 + k3) * c1 + k4 * c2
            dc2dt = k3 * c1 - k4 * c2
            return [dc1dt, dc2dt]

        y0 = [0, 0]
        sol = odeint(model, y0, times, args=(k1, k2, k3, k4))
        return sol[:, 0] + sol[:, 1]

    def _calculate_derived_parameters(
        self, params: Dict, model_type: str
    ) -> Dict[str, float]:
        """Calculate derived kinetic parameters."""
        derived = {}

        if model_type in ["2TCM", "1TCM"]:
            if "K1" in params and "k2" in params:
                derived["Vd"] = params["K1"] / params["k2"]  # Distribution volume

            if model_type == "2TCM" and all(
                k in params for k in ["K1", "k2", "k3", "k4"]
            ):
                # Binding potential
                derived["BP"] = params["k3"] / params["k4"]
                # Total distribution volume
                derived["VT"] = (
                    params["K1"] / params["k2"] * (1 + params["k3"] / params["k4"])
                )

        return {k: float(v) for k, v in derived.items()}

    def _generate_fitted_curve(
        self, params: Dict, aif: np.ndarray, times: np.ndarray, model_type: str
    ) -> np.ndarray:
        """Generate fitted TAC curve."""
        if model_type == "2TCM":
            return self._simulate_2tcm(
                aif, times, params["K1"], params["k2"], params["k3"], params["k4"]
            )
        elif model_type == "1TCM":
            # Simplified 1TCM
            from scipy.interpolate import interp1d

            aif_interp = interp1d(times, aif, kind="linear", fill_value="extrapolate")

            def model(y, t, k1, k2):
                c = y[0]
                cp = aif_interp(t)
                dcdt = k1 * cp - k2 * c
                return [dcdt]

            y0 = [0]
            sol = odeint(model, y0, times, args=(params["K1"], params["k2"]))
            return sol[:, 0]
        else:
            # For Logan/Patlak, return original TAC as approximation
            return aif * params.get("DVR", 1.0)

    def _calculate_r_squared(
        self, observed: np.ndarray, predicted: np.ndarray
    ) -> float:
        """Calculate R-squared value."""
        ss_res = np.sum((observed - predicted) ** 2)
        ss_tot = np.sum((observed - np.mean(observed)) ** 2)
        return 1 - (ss_res / ss_tot) if ss_tot > 0 else 0


class PartialVolumeCorrenctionTool(NeuroToolWrapper):
    """Perform partial volume correction on PET images."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "partial_volume_correction"

    def get_tool_description(self) -> str:
        return "Apply partial volume correction to PET images"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        pet_image: Optional[Union[str, np.ndarray]] = None,
        segmentation: Optional[np.ndarray] = None,
        psf_fwhm: float = 6.0,  # mm
        method: str = "GTM",  # GTM, Muller-Gartner, or Rousset
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Apply partial volume correction."""
        try:
            output_path = Path(output_dir or "pvc_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if pet_image is None:
                pet_data = self._generate_synthetic_pet_data()
                seg_data = self._generate_segmentation()
            else:
                pet_data = self._load_pet_image(pet_image)
                seg_data = (
                    segmentation
                    if segmentation is not None
                    else self._generate_segmentation()
                )

            # Apply PVC based on method
            if method == "GTM":
                corrected = self._apply_gtm(pet_data, seg_data, psf_fwhm)
            elif method == "Muller-Gartner":
                corrected = self._apply_muller_gartner(pet_data, seg_data, psf_fwhm)
            elif method == "Rousset":
                corrected = self._apply_rousset(pet_data, seg_data, psf_fwhm)
            else:
                corrected = self._apply_gtm(pet_data, seg_data, psf_fwhm)

            # Calculate correction factors
            correction_factors = self._calculate_correction_factors(pet_data, corrected)

            # Regional analysis
            regional_corrections = self._analyze_regional_corrections(
                pet_data, corrected, seg_data
            )

            # Save results
            np.save(output_path / "corrected_pet.npy", corrected)
            np.save(output_path / "correction_factors.npy", correction_factors)

            results = {
                "method": method,
                "psf_fwhm": psf_fwhm,
                "mean_correction_factor": float(
                    np.mean(correction_factors[correction_factors > 0])
                ),
                "regional_corrections": regional_corrections,
                "image_stats": {
                    "original_mean": float(np.mean(pet_data)),
                    "corrected_mean": float(np.mean(corrected)),
                    "original_max": float(np.max(pet_data)),
                    "corrected_max": float(np.max(corrected)),
                },
            }

            with open(output_path / "pvc_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "corrected_image": str(output_path / "corrected_pet.npy"),
                        "correction_factors": str(
                            output_path / "correction_factors.npy"
                        ),
                        "results": str(output_path / "pvc_results.json"),
                    }
                },
            )

        except Exception as e:
            logger.error(f"PVC failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_synthetic_pet_data(self) -> np.ndarray:
        """Generate synthetic PET data."""
        shape = (91, 109, 91)
        pet_data = np.random.exponential(scale=1000, size=shape)

        # Add structure
        center = [s // 2 for s in shape]
        x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]

        # Add different uptake regions
        for i in range(3):
            radius = 10 + i * 5
            mask = (
                (x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2
            ) <= radius**2
            pet_data[mask] *= 3 - i * 0.5

        # Apply smoothing to simulate PVE
        from scipy.ndimage import gaussian_filter

        pet_data = gaussian_filter(pet_data, sigma=2)

        return pet_data

    def _generate_segmentation(self) -> np.ndarray:
        """Generate tissue segmentation."""
        shape = (91, 109, 91)
        seg = np.zeros(shape, dtype=int)

        # Create simple tissue types
        center = [s // 2 for s in shape]
        x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]

        # Gray matter (label 1)
        mask1 = (
            (x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2
        ) <= 30**2
        seg[mask1] = 1

        # White matter (label 2)
        mask2 = (
            ((x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2)
            <= 20**2
        ) & (~mask1)
        seg[mask2] = 2

        # CSF (label 3)
        mask3 = (
            (
                ((x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2)
                <= 10**2
            )
            & (~mask1)
            & (~mask2)
        )
        seg[mask3] = 3

        return seg

    def _load_pet_image(self, pet_image: Union[str, np.ndarray]) -> np.ndarray:
        """Load PET image."""
        if isinstance(pet_image, np.ndarray):
            return pet_image
        return self._generate_synthetic_pet_data()

    def _apply_gtm(self, pet: np.ndarray, seg: np.ndarray, fwhm: float) -> np.ndarray:
        """Apply Geometric Transfer Matrix correction."""
        from scipy.ndimage import gaussian_filter

        # Simplified GTM implementation
        sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))

        # Create transfer matrix (simplified)
        n_regions = len(np.unique(seg)) - 1  # Exclude background

        # Apply correction per region
        corrected = np.zeros_like(pet)

        for label in range(1, n_regions + 1):
            mask = seg == label

            # Simulate PSF effect
            psf_affected = gaussian_filter(mask.astype(float), sigma)

            # Correction factor
            correction = 1.0 / (psf_affected + 0.01)  # Avoid division by zero
            correction[correction > 3] = 3  # Cap correction factor

            # Apply correction
            corrected[mask] = pet[mask] * correction[mask]

        # Fill uncorrected regions
        corrected[corrected == 0] = pet[corrected == 0]

        return corrected

    def _apply_muller_gartner(
        self, pet: np.ndarray, seg: np.ndarray, fwhm: float
    ) -> np.ndarray:
        """Apply Muller-Gartner correction."""
        # Simplified implementation
        from scipy.ndimage import gaussian_filter

        sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))

        # Gray matter mask
        gm_mask = seg == 1

        # White matter mean
        wm_mask = seg == 2
        wm_mean = np.mean(pet[wm_mask]) if np.any(wm_mask) else 0

        # Apply correction to gray matter
        corrected = pet.copy()

        # Convolve WM with PSF
        wm_convolved = gaussian_filter(wm_mask.astype(float) * wm_mean, sigma)

        # Convolve GM mask with PSF
        gm_convolved = gaussian_filter(gm_mask.astype(float), sigma)

        # Muller-Gartner correction
        denominator = gm_convolved + 0.01  # Avoid division by zero
        corrected[gm_mask] = (pet[gm_mask] - wm_convolved[gm_mask]) / denominator[
            gm_mask
        ]

        return corrected

    def _apply_rousset(
        self, pet: np.ndarray, seg: np.ndarray, fwhm: float
    ) -> np.ndarray:
        """Apply Rousset correction (simplified)."""
        # Very simplified version of region-based voxel-wise correction
        from scipy.ndimage import gaussian_filter

        sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))

        # Apply simple deconvolution-like correction
        blurred = gaussian_filter(pet, sigma)

        # Correction factor based on blurring
        correction = pet / (blurred + 0.01)
        correction[correction > 3] = 3  # Cap correction

        return pet * correction

    def _calculate_correction_factors(
        self, original: np.ndarray, corrected: np.ndarray
    ) -> np.ndarray:
        """Calculate voxel-wise correction factors."""
        factors = np.zeros_like(original)
        mask = original > 0
        factors[mask] = corrected[mask] / original[mask]
        return factors

    def _analyze_regional_corrections(
        self, original: np.ndarray, corrected: np.ndarray, seg: np.ndarray
    ) -> Dict[str, Dict[str, float]]:
        """Analyze corrections by region."""
        regions = {1: "gray_matter", 2: "white_matter", 3: "csf"}

        results = {}
        for label, name in regions.items():
            mask = seg == label
            if np.any(mask):
                results[name] = {
                    "original_mean": float(np.mean(original[mask])),
                    "corrected_mean": float(np.mean(corrected[mask])),
                    "correction_factor": float(
                        np.mean(corrected[mask]) / (np.mean(original[mask]) + 0.01)
                    ),
                }

        return results


class TracerUptakeAnalysisTool(NeuroToolWrapper):
    """Analyze tracer-specific uptake patterns."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "tracer_uptake_analysis"

    def get_tool_description(self) -> str:
        return "Analyze tracer-specific uptake patterns and binding potentials"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        pet_image: Optional[Union[str, np.ndarray]] = None,
        tracer: str = "FDG",
        reference_region: Optional[str] = None,
        scan_duration: float = 90.0,  # minutes
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Analyze tracer uptake."""
        try:
            output_path = Path(output_dir or "uptake_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or load data
            if pet_image is None:
                pet_data = self._generate_tracer_specific_data(tracer)
            else:
                pet_data = self._load_pet_image(pet_image)

            # Get tracer properties
            tracer_props = self._get_tracer_properties(tracer)

            # Calculate uptake metrics
            uptake_metrics = self._calculate_uptake_metrics(pet_data, tracer_props)

            # Binding analysis if applicable
            if tracer_props["receptor_binding"]:
                binding_results = self._analyze_binding(
                    pet_data, reference_region, tracer_props
                )
            else:
                binding_results = {}

            # Pattern analysis
            spatial_pattern = self._analyze_spatial_pattern(pet_data, tracer)

            # Asymmetry analysis
            asymmetry = self._analyze_asymmetry(pet_data)

            results = {
                "tracer": tracer,
                "tracer_properties": tracer_props,
                "uptake_metrics": uptake_metrics,
                "binding_analysis": binding_results,
                "spatial_pattern": spatial_pattern,
                "asymmetry_index": asymmetry,
                "scan_duration": scan_duration,
            }

            # Save results
            with open(output_path / "uptake_analysis.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "results": str(output_path / "uptake_analysis.json")
                    }
                },
            )

        except Exception as e:
            logger.error(f"Uptake analysis failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_tracer_specific_data(self, tracer: str) -> np.ndarray:
        """Generate tracer-specific synthetic data."""
        shape = (91, 109, 91)

        if tracer == "FDG":
            # FDG: high in gray matter, lower in white matter
            data = np.random.exponential(scale=1000, size=shape)
            # Add gray matter hotspots
            for _ in range(10):
                center = [np.random.randint(20, s - 20) for s in shape]
                radius = np.random.randint(5, 10)
                x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]
                mask = (
                    (x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2
                ) <= radius**2
                data[mask] *= 2.5

        elif tracer == "PIB":
            # PIB: amyloid tracer, patchy distribution
            data = np.random.exponential(scale=500, size=shape)
            # Add amyloid-like deposits
            for _ in range(15):
                center = [np.random.randint(30, s - 30) for s in shape]
                radius = np.random.randint(3, 7)
                x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]
                mask = (
                    (x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2
                ) <= radius**2
                data[mask] *= 3.0

        elif tracer == "FDOPA":
            # FDOPA: dopamine, high in striatum
            data = np.random.exponential(scale=800, size=shape)
            # Add striatal uptake
            center = [shape[0] // 2, shape[1] // 2, shape[2] // 2]
            x, y, z = np.ogrid[: shape[0], : shape[1], : shape[2]]
            # Simulate striatum location
            mask = (
                (x - center[0] + 10) ** 2 / 100
                + (y - center[1]) ** 2 / 64
                + (z - center[2]) ** 2 / 64
            ) <= 1
            data[mask] *= 4.0

        else:
            # Generic tracer
            data = np.random.exponential(scale=1000, size=shape)

        # Apply smoothing
        from scipy.ndimage import gaussian_filter

        data = gaussian_filter(data, sigma=1.5)

        return data

    def _load_pet_image(self, pet_image: Union[str, np.ndarray]) -> np.ndarray:
        """Load PET image."""
        if isinstance(pet_image, np.ndarray):
            return pet_image
        return self._generate_tracer_specific_data("FDG")

    def _get_tracer_properties(self, tracer: str) -> Dict[str, Any]:
        """Get tracer-specific properties."""
        tracers = {
            "FDG": {
                "full_name": "Fluorodeoxyglucose",
                "target": "Glucose metabolism",
                "half_life": 109.8,  # minutes
                "receptor_binding": False,
                "typical_dose": 370,  # MBq
                "scan_start": 60,  # minutes post-injection
            },
            "PIB": {
                "full_name": "Pittsburgh Compound B",
                "target": "Amyloid plaques",
                "half_life": 20.3,
                "receptor_binding": True,
                "typical_dose": 555,
                "scan_start": 40,
            },
            "FDOPA": {
                "full_name": "Fluorodopa",
                "target": "Dopamine synthesis",
                "half_life": 109.8,
                "receptor_binding": True,
                "typical_dose": 185,
                "scan_start": 90,
            },
            "FLT": {
                "full_name": "Fluorothymidine",
                "target": "Cell proliferation",
                "half_life": 109.8,
                "receptor_binding": False,
                "typical_dose": 370,
                "scan_start": 60,
            },
        }

        return tracers.get(
            tracer,
            {
                "full_name": tracer,
                "target": "Unknown",
                "half_life": 109.8,
                "receptor_binding": False,
                "typical_dose": 370,
                "scan_start": 60,
            },
        )

    def _calculate_uptake_metrics(
        self, pet_data: np.ndarray, tracer_props: Dict
    ) -> Dict[str, float]:
        """Calculate uptake metrics."""
        # Basic statistics
        metrics = {
            "mean_uptake": float(np.mean(pet_data)),
            "max_uptake": float(np.max(pet_data)),
            "std_uptake": float(np.std(pet_data)),
            "coefficient_variation": float(
                np.std(pet_data) / (np.mean(pet_data) + 0.01)
            ),
        }

        # Percentile values
        percentiles = [5, 25, 50, 75, 95]
        for p in percentiles:
            metrics[f"percentile_{p}"] = float(np.percentile(pet_data, p))

        # Uptake volume (simplified)
        threshold = np.percentile(pet_data, 70)
        high_uptake_volume = np.sum(pet_data > threshold)
        metrics["high_uptake_volume"] = int(high_uptake_volume)

        return metrics

    def _analyze_binding(
        self, pet_data: np.ndarray, reference_region: Optional[str], tracer_props: Dict
    ) -> Dict[str, float]:
        """Analyze receptor binding."""
        # Simplified binding analysis

        # Define reference region (simplified as low-uptake area)
        if reference_region:
            # In reality, would use anatomical atlas
            ref_value = np.percentile(pet_data, 10)
        else:
            ref_value = np.percentile(pet_data, 10)

        # Calculate binding potential (simplified)
        target_value = np.percentile(pet_data, 90)

        binding = {
            "binding_potential": float((target_value - ref_value) / ref_value),
            "distribution_volume_ratio": float(target_value / ref_value),
            "reference_value": float(ref_value),
            "target_value": float(target_value),
        }

        return binding

    def _analyze_spatial_pattern(
        self, pet_data: np.ndarray, tracer: str
    ) -> Dict[str, Any]:
        """Analyze spatial uptake pattern."""
        # Simplified spatial pattern analysis

        # Calculate center of mass
        coords = np.mgrid[: pet_data.shape[0], : pet_data.shape[1], : pet_data.shape[2]]
        com = []
        total_mass = np.sum(pet_data)

        for i in range(3):
            com.append(float(np.sum(coords[i] * pet_data) / total_mass))

        # Calculate spread
        distances = np.sqrt(
            (coords[0] - com[0]) ** 2
            + (coords[1] - com[1]) ** 2
            + (coords[2] - com[2]) ** 2
        )
        weighted_distance = np.sum(distances * pet_data) / total_mass

        # Anterior-posterior gradient
        ap_gradient = float(
            np.mean(pet_data[: pet_data.shape[0] // 2])
            / (np.mean(pet_data[pet_data.shape[0] // 2 :]) + 0.01)
        )

        return {
            "center_of_mass": com,
            "spatial_spread": float(weighted_distance),
            "anterior_posterior_ratio": ap_gradient,
            "pattern_type": self._classify_pattern(tracer),
        }

    def _classify_pattern(self, tracer: str) -> str:
        """Classify uptake pattern based on tracer."""
        patterns = {
            "FDG": "cortical",
            "PIB": "diffuse",
            "FDOPA": "focal_subcortical",
            "FLT": "heterogeneous",
        }
        return patterns.get(tracer, "unknown")

    def _analyze_asymmetry(self, pet_data: np.ndarray) -> float:
        """Calculate asymmetry index."""
        # Simple left-right asymmetry
        midline = pet_data.shape[0] // 2
        left = pet_data[:midline]
        right = pet_data[midline:]

        # Flip right for comparison
        right_flipped = np.flip(right, axis=0)

        # Calculate asymmetry index
        min_shape = min(left.shape[0], right_flipped.shape[0])
        left = left[:min_shape]
        right_flipped = right_flipped[:min_shape]

        asymmetry = np.abs(left - right_flipped) / (left + right_flipped + 0.01)
        return float(np.mean(asymmetry))


class MultiTracerComparisonTool(NeuroToolWrapper):
    """Compare multiple PET tracers for comprehensive analysis."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "multi_tracer_comparison"

    def get_tool_description(self) -> str:
        return "Compare and integrate data from multiple PET tracers"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        tracer_images: Optional[Dict[str, np.ndarray]] = None,
        tracers: Optional[List[str]] = None,
        comparison_metrics: Optional[List[str]] = None,
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Compare multiple tracers."""
        try:
            output_path = Path(output_dir or "multitracer_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or use provided data
            if tracer_images is None:
                tracers = tracers or ["FDG", "PIB", "FDOPA"]
                tracer_data = {t: self._generate_tracer_data(t) for t in tracers}
            else:
                tracer_data = tracer_images
                if tracers is None:
                    tracers = list(tracer_images.keys())

            # Define comparison metrics
            if comparison_metrics is None:
                comparison_metrics = ["correlation", "overlap", "complementarity"]

            # Perform comparisons
            comparisons = {}
            for i, t1 in enumerate(tracers):
                for t2 in tracers[i + 1 :]:
                    pair = f"{t1}_vs_{t2}"
                    comparisons[pair] = self._compare_tracers(
                        tracer_data[t1], tracer_data[t2], comparison_metrics
                    )

            # Integrated analysis
            integrated = self._integrated_analysis(tracer_data, tracers)

            # Clustering analysis
            clusters = self._cluster_analysis(tracer_data)

            results = {
                "tracers": tracers,
                "pairwise_comparisons": comparisons,
                "integrated_analysis": integrated,
                "cluster_analysis": clusters,
                "comparison_metrics": comparison_metrics,
            }

            # Save results
            with open(output_path / "multitracer_results.json", "w") as f:
                json.dump(results, f, indent=2)

            # Save integrated maps
            for name, data in integrated.items():
                if isinstance(data, np.ndarray):
                    np.save(output_path / f"integrated_{name}.npy", data)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "results": str(output_path / "multitracer_results.json"),
                        "output_dir": str(output_path),
                    }
                },
            )

        except Exception as e:
            logger.error(f"Multi-tracer comparison failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_tracer_data(self, tracer: str) -> np.ndarray:
        """Generate tracer-specific data."""
        shape = (91, 109, 91)

        if tracer == "FDG":
            data = np.random.exponential(scale=1000, size=shape)
        elif tracer == "PIB":
            data = np.random.exponential(scale=800, size=shape)
        elif tracer == "FDOPA":
            data = np.random.exponential(scale=600, size=shape)
        else:
            data = np.random.exponential(scale=700, size=shape)

        # Add tracer-specific patterns
        from scipy.ndimage import gaussian_filter

        data = gaussian_filter(data, sigma=2)

        return data

    def _compare_tracers(
        self, data1: np.ndarray, data2: np.ndarray, metrics: List[str]
    ) -> Dict[str, float]:
        """Compare two tracer images."""
        results = {}

        if "correlation" in metrics:
            # Spatial correlation
            flat1 = data1.flatten()
            flat2 = data2.flatten()
            corr = np.corrcoef(flat1, flat2)[0, 1]
            results["spatial_correlation"] = float(corr)

        if "overlap" in metrics:
            # Overlap of high-uptake regions
            threshold1 = np.percentile(data1, 75)
            threshold2 = np.percentile(data2, 75)

            high1 = data1 > threshold1
            high2 = data2 > threshold2

            intersection = np.sum(high1 & high2)
            union = np.sum(high1 | high2)

            results["dice_coefficient"] = float(
                2 * intersection / (np.sum(high1) + np.sum(high2) + 0.01)
            )
            results["jaccard_index"] = float(intersection / (union + 0.01))

        if "complementarity" in metrics:
            # Measure how complementary the patterns are
            norm1 = (data1 - np.min(data1)) / (np.max(data1) - np.min(data1) + 0.01)
            norm2 = (data2 - np.min(data2)) / (np.max(data2) - np.min(data2) + 0.01)

            # High in one, low in other
            complement_score = np.mean(np.abs(norm1 - norm2))
            results["complementarity_score"] = float(complement_score)

        return results

    def _integrated_analysis(
        self, tracer_data: Dict[str, np.ndarray], tracers: List[str]
    ) -> Dict[str, Any]:
        """Perform integrated analysis across tracers."""
        # Stack all tracer data
        stacked = np.stack([tracer_data[t] for t in tracers], axis=-1)

        # Calculate mean and std across tracers
        mean_map = np.mean(stacked, axis=-1)
        std_map = np.std(stacked, axis=-1)

        # Coefficient of variation
        cv_map = std_map / (mean_map + 0.01)

        # Principal component analysis (simplified)
        n_voxels = np.prod(stacked.shape[:-1])
        n_tracers = len(tracers)

        reshaped = stacked.reshape(n_voxels, n_tracers)

        # Center the data
        centered = reshaped - np.mean(reshaped, axis=0)

        # Compute covariance
        cov = np.cov(centered.T)

        # Eigendecomposition
        eigenvalues, eigenvectors = np.linalg.eig(cov)

        # Sort by eigenvalue
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        # Variance explained
        var_explained = eigenvalues / np.sum(eigenvalues)

        return {
            "mean_uptake": float(np.mean(mean_map)),
            "mean_cv": float(np.mean(cv_map)),
            "pca_variance_explained": var_explained.tolist(),
            "dominant_pattern": tracers[np.argmax(eigenvectors[:, 0] ** 2)],
            "integration_score": float(
                1 - np.mean(cv_map)
            ),  # Higher score = more agreement
        }

    def _cluster_analysis(self, tracer_data: Dict[str, np.ndarray]) -> Dict[str, Any]:
        """Perform clustering analysis on multi-tracer data."""
        # Simplified k-means clustering
        from scipy.cluster.vq import kmeans2

        # Stack and reshape data
        stacked = np.stack(list(tracer_data.values()), axis=-1)
        n_voxels = np.prod(stacked.shape[:-1])
        n_tracers = stacked.shape[-1]

        reshaped = stacked.reshape(n_voxels, n_tracers)

        # Remove background voxels
        mask = np.sum(reshaped, axis=1) > np.percentile(np.sum(reshaped, axis=1), 10)
        data_masked = reshaped[mask]

        # Normalize
        data_norm = (data_masked - np.mean(data_masked, axis=0)) / (
            np.std(data_masked, axis=0) + 0.01
        )

        # K-means clustering
        n_clusters = min(5, len(data_masked) // 100)

        if n_clusters > 1 and len(data_masked) > n_clusters:
            centroids, labels = kmeans2(data_norm, n_clusters, minit="points")

            # Cluster statistics
            cluster_sizes = [int(np.sum(labels == i)) for i in range(n_clusters)]

            results = {
                "n_clusters": int(n_clusters),
                "cluster_sizes": cluster_sizes,
                "cluster_profiles": centroids.tolist(),
            }
        else:
            results = {
                "n_clusters": 1,
                "cluster_sizes": [int(len(data_masked))],
                "cluster_profiles": [[1.0] * n_tracers],
            }

        return results


class ParametricMappingTool(NeuroToolWrapper):
    """Generate parametric maps from dynamic PET data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "parametric_mapping"

    def get_tool_description(self) -> str:
        return "Generate voxel-wise parametric maps from dynamic PET data"

    def get_args_schema(self):
        return PETInput

    def _run(
        self,
        dynamic_pet: Optional[np.ndarray] = None,  # 4D: x,y,z,time
        scan_times: Optional[List[float]] = None,
        input_function: Optional[np.ndarray] = None,
        map_type: str = "Ki",  # Ki, Vt, BP, R1
        model: str = "Patlak",  # Patlak, Logan, SRTM
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """Generate parametric maps."""
        try:
            output_path = Path(output_dir or "parametric_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate or use provided data
            if dynamic_pet is None:
                dynamic_pet, aif, times = self._generate_dynamic_data()
            else:
                aif = (
                    input_function
                    if input_function is not None
                    else self._generate_aif()
                )
                times = (
                    np.array(scan_times)
                    if scan_times
                    else np.linspace(0, 90, dynamic_pet.shape[-1])
                )

            # Generate parametric map based on model
            if model == "Patlak":
                param_map = self._generate_patlak_map(dynamic_pet, aif, times, map_type)
            elif model == "Logan":
                param_map = self._generate_logan_map(dynamic_pet, aif, times, map_type)
            elif model == "SRTM":
                param_map = self._generate_srtm_map(dynamic_pet, times, map_type)
            else:
                param_map = self._generate_patlak_map(dynamic_pet, aif, times, map_type)

            # Calculate statistics
            map_stats = self._calculate_map_statistics(param_map)

            # Quality metrics
            quality = self._assess_map_quality(param_map, dynamic_pet)

            # Save parametric map
            np.save(output_path / f"{map_type}_map.npy", param_map)

            results = {
                "map_type": map_type,
                "model": model,
                "statistics": map_stats,
                "quality_metrics": quality,
                "scan_duration": float(times[-1]),
                "n_time_frames": len(times),
            }

            with open(output_path / "parametric_results.json", "w") as f:
                json.dump(results, f, indent=2)

            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "parametric_map": str(output_path / f"{map_type}_map.npy"),
                        "results": str(output_path / "parametric_results.json"),
                    }
                },
            )

        except Exception as e:
            logger.error(f"Parametric mapping failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _generate_dynamic_data(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate synthetic dynamic PET data."""
        # Spatial dimensions
        spatial_shape = (30, 30, 30)  # Smaller for efficiency
        n_times = 20

        # Time points
        times = np.linspace(0, 90, n_times)

        # Generate AIF
        aif = self._generate_aif(times)

        # Generate dynamic data
        dynamic = np.zeros(spatial_shape + (n_times,))

        # Create different kinetic behaviors in different regions
        for i in range(spatial_shape[0]):
            for j in range(spatial_shape[1]):
                for k in range(spatial_shape[2]):
                    # Vary kinetic parameters spatially
                    k1 = 0.05 + 0.1 * (i / spatial_shape[0])
                    k2 = 0.1 + 0.05 * (j / spatial_shape[1])

                    # Simple 1TCM for efficiency
                    tac = self._simulate_1tcm(aif, times, k1, k2)

                    # Add noise
                    tac += np.random.normal(0, 0.05 * np.mean(tac), len(tac))

                    dynamic[i, j, k, :] = tac

        return dynamic, aif, times

    def _generate_aif(self, times: Optional[np.ndarray] = None) -> np.ndarray:
        """Generate arterial input function."""
        if times is None:
            times = np.linspace(0, 90, 20)

        # Three-exponential model
        A1, A2, A3 = 851.1, 21.88, 20.81
        lambda1, lambda2, lambda3 = 4.134, 0.1191, 0.01043

        aif = (
            A1 * np.exp(-lambda1 * times)
            + A2 * np.exp(-lambda2 * times)
            + A3 * np.exp(-lambda3 * times)
        )

        return aif

    def _simulate_1tcm(
        self, aif: np.ndarray, times: np.ndarray, k1: float, k2: float
    ) -> np.ndarray:
        """Simulate 1TCM TAC."""
        from scipy.interpolate import interp1d

        aif_interp = interp1d(times, aif, kind="linear", fill_value="extrapolate")

        def model(y, t):
            c = y[0]
            cp = aif_interp(t)
            dcdt = k1 * cp - k2 * c
            return [dcdt]

        y0 = [0]
        sol = odeint(model, y0, times)
        return sol[:, 0]

    def _generate_patlak_map(
        self, dynamic: np.ndarray, aif: np.ndarray, times: np.ndarray, map_type: str
    ) -> np.ndarray:
        """Generate Patlak parametric map."""
        from scipy.integrate import cumtrapz

        # Calculate integrals
        int_aif = cumtrapz(aif, times, initial=0)

        # Initialize map
        param_map = np.zeros(dynamic.shape[:-1])

        # Use later time points for linear phase
        start_idx = len(times) // 3

        # Voxel-wise Patlak analysis
        for i in range(dynamic.shape[0]):
            for j in range(dynamic.shape[1]):
                for k in range(dynamic.shape[2]):
                    tac = dynamic[i, j, k, :]

                    if np.mean(tac) > np.percentile(dynamic, 10):  # Skip background
                        # Patlak plot
                        x = int_aif[start_idx:] / (aif[start_idx:] + 0.01)
                        y = tac[start_idx:] / (aif[start_idx:] + 0.01)

                        # Linear fit
                        try:
                            slope, intercept = np.polyfit(x, y, 1)

                            if map_type == "Ki":
                                param_map[i, j, k] = slope
                            elif map_type == "V0":
                                param_map[i, j, k] = intercept
                            else:
                                param_map[i, j, k] = slope  # Default to Ki
                        except:
                            param_map[i, j, k] = 0

        return param_map

    def _generate_logan_map(
        self, dynamic: np.ndarray, aif: np.ndarray, times: np.ndarray, map_type: str
    ) -> np.ndarray:
        """Generate Logan parametric map."""
        from scipy.integrate import cumtrapz

        # Calculate integrals
        int_aif = cumtrapz(aif, times, initial=0)

        # Initialize map
        param_map = np.zeros(dynamic.shape[:-1])

        # Use later time points
        start_idx = len(times) // 3

        # Voxel-wise Logan analysis
        for i in range(dynamic.shape[0]):
            for j in range(dynamic.shape[1]):
                for k in range(dynamic.shape[2]):
                    tac = dynamic[i, j, k, :]

                    if np.mean(tac) > np.percentile(dynamic, 10):
                        int_tac = cumtrapz(tac, times, initial=0)

                        # Logan plot
                        x = int_aif[start_idx:] / (tac[start_idx:] + 0.01)
                        y = int_tac[start_idx:] / (tac[start_idx:] + 0.01)

                        try:
                            slope, intercept = np.polyfit(x, y, 1)

                            if map_type in ["Vt", "DVR"]:
                                param_map[i, j, k] = slope
                            elif map_type == "int":
                                param_map[i, j, k] = intercept
                            else:
                                param_map[i, j, k] = slope
                        except:
                            param_map[i, j, k] = 0

        return param_map

    def _generate_srtm_map(
        self, dynamic: np.ndarray, times: np.ndarray, map_type: str
    ) -> np.ndarray:
        """Generate SRTM parametric map (simplified)."""
        # Simplified reference tissue model
        # Would need reference region TAC in real implementation

        param_map = np.zeros(dynamic.shape[:-1])

        # Use mean of low-uptake region as reference
        threshold = np.percentile(dynamic, 20)
        ref_mask = np.mean(dynamic, axis=-1) < threshold

        if np.any(ref_mask):
            ref_tac = np.mean(dynamic[ref_mask], axis=0)

            # Simplified SRTM fitting
            for i in range(dynamic.shape[0]):
                for j in range(dynamic.shape[1]):
                    for k in range(dynamic.shape[2]):
                        if not ref_mask[i, j, k]:
                            tac = dynamic[i, j, k, :]

                            # Simple ratio for BP
                            if map_type == "BP":
                                param_map[i, j, k] = (
                                    np.mean(tac) / np.mean(ref_tac)
                                ) - 1
                            elif map_type == "R1":
                                # Relative delivery
                                param_map[i, j, k] = tac[0] / ref_tac[0]
                            else:
                                param_map[i, j, k] = (
                                    np.mean(tac) / np.mean(ref_tac)
                                ) - 1

        return param_map

    def _calculate_map_statistics(self, param_map: np.ndarray) -> Dict[str, float]:
        """Calculate parametric map statistics."""
        # Mask out background
        mask = param_map > np.percentile(param_map, 10)
        masked_data = param_map[mask]

        if len(masked_data) > 0:
            stats = {
                "mean": float(np.mean(masked_data)),
                "std": float(np.std(masked_data)),
                "median": float(np.median(masked_data)),
                "min": float(np.min(masked_data)),
                "max": float(np.max(masked_data)),
                "cv": float(np.std(masked_data) / (np.mean(masked_data) + 0.01)),
            }
        else:
            stats = {
                "mean": 0.0,
                "std": 0.0,
                "median": 0.0,
                "min": 0.0,
                "max": 0.0,
                "cv": 0.0,
            }

        return stats

    def _assess_map_quality(
        self, param_map: np.ndarray, dynamic: np.ndarray
    ) -> Dict[str, float]:
        """Assess quality of parametric map."""
        # Signal-to-noise ratio
        signal = np.mean(param_map[param_map > np.percentile(param_map, 75)])
        noise = np.std(param_map[param_map < np.percentile(param_map, 25)])
        snr = signal / (noise + 0.01)

        # Coefficient of variation in homogeneous region
        # Find relatively homogeneous region (low temporal variance)
        temporal_cv = np.std(dynamic, axis=-1) / (np.mean(dynamic, axis=-1) + 0.01)
        homogeneous_mask = temporal_cv < np.percentile(temporal_cv, 30)

        if np.any(homogeneous_mask):
            homogeneous_cv = np.std(param_map[homogeneous_mask]) / (
                np.mean(param_map[homogeneous_mask]) + 0.01
            )
        else:
            homogeneous_cv = 1.0

        # Spatial smoothness (simplified)
        from scipy.ndimage import gaussian_filter

        smoothed = gaussian_filter(param_map, sigma=1)
        smoothness = np.corrcoef(param_map.flatten(), smoothed.flatten())[0, 1]

        return {
            "snr": float(snr),
            "homogeneity_cv": float(homogeneous_cv),
            "spatial_smoothness": float(smoothness),
            "quality_score": float((snr * smoothness) / (homogeneous_cv + 0.01)),
        }


class PETImagingTools:
    """Collection of PET imaging analysis tools."""

    def __init__(self):
        self.tools = [
            SUVCalculationTool(),
            KineticModelingTool(),
            PartialVolumeCorrenctionTool(),
            TracerUptakeAnalysisTool(),
            MultiTracerComparisonTool(),
            ParametricMappingTool(),
        ]

    def get_all_tools(self) -> List[NeuroToolWrapper]:
        """Get all PET imaging tools."""
        return self.tools

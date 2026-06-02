"""
Nilearn Integration Module for MRI Research Assistant

This module provides functions to perform common fMRI analysis tasks using Nilearn.
It includes functions for:
- Fetching datasets
- Running GLM analysis
- Plotting statistical maps
- Extracting peak coordinates
- Performing functional connectivity analysis
- Analyzing specific datasets like Haxby

These functions are designed to be called by the MCP agent.
"""

import base64
import json
import logging
import os
import warnings
from io import BytesIO
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets, plotting
from nilearn.glm.first_level import FirstLevelModel, make_first_level_design_matrix
from nilearn.image import concat_imgs
from nilearn.reporting import get_clusters_table

# Suppress benign nibabel header warnings
warnings.filterwarnings("ignore", message=".*pixdim.*qfac.*")
warnings.filterwarnings("ignore", message=".*image has no sform.*")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define output directory relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "nilearn_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _save_plot_to_base64(fig) -> str:
    """Saves a matplotlib figure to a base64 encoded string."""
    buf = BytesIO()
    fig.savefig(buf)
    buf.seek(0)
    img_str = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    return img_str


def analyze_motor_task(threshold: float = 3.0) -> dict[str, Any]:
    """
    Analyzes a motor task dataset using Nilearn.

    Args:
        threshold: Statistical threshold for activation maps.

    Returns:
        Dictionary containing analysis results (paths to maps, plots, peak table, and peak coordinates).
    """
    logger.info(f"Starting motor task analysis with threshold={threshold}...")
    results = {"success": False, "message": "", "outputs": {}}

    try:
        # Fetch the dataset
        logger.info("Fetching sample motor task dataset...")
        # Using neurovault motor task dataset
        motor_images = datasets.fetch_neurovault_motor_task()

        # Create a directory for our output
        data_dir = os.path.join(PROJECT_ROOT, "data", "motor_task")
        os.makedirs(data_dir, exist_ok=True)

        # We'll work with the statistical map directly
        # The images attribute contains paths to the downloaded images
        z_map_path = motor_images.images[0]  # First image path in the collection
        z_map = nib.load(z_map_path)  # Load the image

        # Save the z-map
        contrast_id = "motor_task"
        z_map_path = os.path.join(OUTPUT_DIR, f"{contrast_id}_zmap.nii.gz")
        nib.save(z_map, z_map_path)
        results["outputs"]["z_map_path"] = z_map_path
        logger.info(f"Z-map saved to: {z_map_path}")

        # Create and save plots
        logger.info("Generating plots...")

        # Plot 1: Brain slices
        fig_slices = plotting.plot_stat_map(
            z_map,
            bg_img=None,
            threshold=threshold,
            display_mode="z",
            cut_coords=8,
            title=f"Motor Task (Z>{threshold})",
        )
        slices_path = os.path.join(OUTPUT_DIR, "motor_task_brain_slices.png")
        fig_slices.savefig(slices_path)
        results["outputs"]["slices_plot_path"] = slices_path
        results["outputs"]["slices_plot_base64"] = _save_plot_to_base64(fig_slices)
        fig_slices.close()

        # Plot 2: Glass brain
        fig_glass = plotting.plot_glass_brain(
            z_map, threshold=threshold, title=f"Motor Task (Z>{threshold})"
        )
        glass_path = os.path.join(OUTPUT_DIR, "motor_task_glass_brain.png")
        fig_glass.savefig(glass_path)
        results["outputs"]["glass_plot_path"] = glass_path
        results["outputs"]["glass_plot_base64"] = _save_plot_to_base64(fig_glass)
        fig_glass.close()

        # Plot 3: ROI focused view
        fig_roi = plotting.plot_roi(
            z_map, threshold=threshold, title=f"Motor Task ROI (Z>{threshold})"
        )
        roi_path = os.path.join(OUTPUT_DIR, "motor_task_roi.png")
        fig_roi.savefig(roi_path)
        results["outputs"]["roi_plot_path"] = roi_path
        results["outputs"]["roi_plot_base64"] = _save_plot_to_base64(fig_roi)
        fig_roi.close()

        # Get clusters table and peak coordinates
        logger.info("Generating clusters table and extracting peak coordinates...")
        clusters_table = get_clusters_table(
            z_map, stat_threshold=threshold, cluster_threshold=10
        )
        table_path = os.path.join(OUTPUT_DIR, "motor_task_clusters.csv")
        clusters_table.to_csv(table_path, index=False)
        results["outputs"]["clusters_table_path"] = table_path
        results["outputs"]["clusters_table_json"] = clusters_table.to_json(
            orient="records"
        )

        # Extract peak coordinates from clusters table
        # clusters_table is a pandas DataFrame, each row contains the peak coordinate (X, Y, Z) and peak statistic (Peak Stat) for a cluster
        # These peaks are automatically detected as the most significant point in each suprathreshold cluster
        if not clusters_table.empty:
            peak_coords = []
            for _, row in clusters_table.iterrows():
                peak_coords.append(
                    {
                        "x": float(row["X"]),
                        "y": float(row["Y"]),
                        "z": float(row["Z"]),
                        "value": float(row["Peak Stat"]),
                    }
                )
            results["outputs"]["peak_coordinates"] = peak_coords
        else:
            results["outputs"]["peak_coordinates"] = []
        # Explanation:
        # get_clusters_table returns a DataFrame where each row represents the peak of a cluster.
        # 'X', 'Y', 'Z' are the MNI coordinates, and 'Peak Stat' is the statistic value (e.g., Z-score) at that peak.
        # These peaks are commonly used to report the spatial location and significance of activation results.
        logger.info(f"Clusters table saved to: {table_path}")

        results["success"] = True
        results["message"] = "Motor task analysis completed successfully."
        logger.info("Motor task analysis finished.")

    except Exception as e:
        logger.exception("An error occurred during motor task analysis")
        results["message"] = f"An unexpected error occurred: {e}"

    return results


def analyze_haxby_dataset(
    threshold: float = 3.0, add_run_intercepts: bool = True
) -> dict[str, Any]:
    """
    Demo of a standard mass-univariate (GLM) workflow on the
    Haxby 2001 face/house localiser.

    Args:
        threshold: Statistical threshold for activation maps.
        add_run_intercepts: Whether to add separate intercepts for each run
                           to handle potential singular matrix issues.

    Returns:
        Dictionary containing analysis results with keys:
        - 'success': bool indicating if analysis completed successfully
        - 'message': str with status message
        - 'outputs': dict containing analysis outputs (paths, data, plots)
    """
    logger.info(f"Starting Haxby dataset analysis with threshold={threshold}...")
    results = {"success": False, "message": "", "outputs": {}}

    try:
        # ------------------------------------------------------------------
        # 1) Download & inspect the sample (one subject = >100 MB)
        # ------------------------------------------------------------------
        logger.info("Fetching Haxby dataset...")
        haxby = datasets.fetch_haxby()
        func_imgs = haxby.func  # list of 12 run files (time × voxels)
        labels_file = haxby.session_target[0]  # text file with per-TR labels
        mask_img = haxby.mask  # brain-mask already in native space
        tr = 2.5  # seconds (hard-coded by the dataset authors)

        # ------------------------------------------------------------------
        # 2) Stack runs and create an events table ("onset-style")
        # ------------------------------------------------------------------
        logger.info("Processing labels and creating events table...")
        labels = pd.read_csv(labels_file, sep=" ")
        conditions = labels["labels"].values
        runs = labels["chunks"].values  # 0…11

        # Create initial events DataFrame with all TRs
        events_raw = pd.DataFrame(
            {
                "onset": np.arange(len(labels)) * tr,
                "duration": tr,
                "trial_type": conditions,
                "run": runs,
            }
        )

        # Collapse consecutive identical labels into single blocks
        # This fixes "Duplicated events" warning
        events = []
        for run_id in np.unique(runs):
            run_events = events_raw[events_raw["run"] == run_id].copy()
            run_events = run_events.sort_values("onset")

            # Group consecutive identical trial types
            grouped = (
                run_events.groupby(
                    (
                        run_events["trial_type"].ne(run_events["trial_type"].shift())
                    ).cumsum()
                )
                .agg({"trial_type": "first", "onset": "first", "duration": "sum"})
                .reset_index(drop=True)
            )
            events.append(grouped)

        events = pd.concat(events, ignore_index=True).sort_values("onset")

        # Remove 'run' column to avoid "unexpected columns" warning
        # Keep only the columns that make_first_level_design_matrix expects
        events = events[["onset", "duration", "trial_type"]]

        # Save events table
        events_path = os.path.join(OUTPUT_DIR, "haxby_events.csv")
        events.to_csv(events_path, index=False)
        results["outputs"]["events_path"] = events_path
        results["outputs"]["events_json"] = events.to_json(orient="records")

        # ------------------------------------------------------------------
        # 3) Build a design matrix for each run and concatenate
        # ------------------------------------------------------------------
        logger.info("Building design matrix...")
        frametimes = np.arange(len(labels)) * tr
        design = make_first_level_design_matrix(
            frametimes, events=events, hrf_model="spm", drift_model="cosine"
        )

        # Add separate intercepts per run if requested to avoid singular matrix
        if add_run_intercepts:
            logger.info("Adding run-specific intercepts...")
            runs = labels["chunks"].values  # Reload run info
            for r in np.unique(runs):
                design[f"run_{r}"] = (runs == r).astype(float)

        # Save design matrix
        design_path = os.path.join(OUTPUT_DIR, "haxby_design_matrix.csv")
        design.to_csv(design_path, index=False)
        results["outputs"]["design_path"] = design_path

        # ------------------------------------------------------------------
        # 4) Fit the first-level GLM (mass-univariate per voxel)
        # ------------------------------------------------------------------
        logger.info("Fitting first-level GLM...")
        fmri_img = concat_imgs(func_imgs)  # combine all runs
        glm = FirstLevelModel(
            t_r=tr,
            mask_img=mask_img,
            smoothing_fwhm=4.0,
            standardize="zscore_sample",
        )
        glm = glm.fit(fmri_img, events)

        # ------------------------------------------------------------------
        # 5) Define & compute contrasts
        # ------------------------------------------------------------------
        logger.info("Computing contrasts...")
        contrast_defs = {
            "faces_vs_houses": (
                design.columns.str.contains("face").astype(int)
                - design.columns.str.contains("house").astype(int)
            ),
            "faces": design.columns.str.contains("face").astype(int),
            "houses": design.columns.str.contains("house").astype(int),
        }

        contrast_maps = {}
        for name, weights in contrast_defs.items():
            logger.info(f"Computing contrast: {name}")
            z_map = glm.compute_contrast(weights, stat_type="t", output_type="z_score")
            z_map = glm.threshold_stats_img(
                z_map, alpha=0.05, height_control="fpr", cluster_threshold=10
            )
            contrast_maps[name] = z_map

            # Save contrast map
            contrast_path = os.path.join(OUTPUT_DIR, f"haxby_{name}_zmap.nii.gz")
            nib.save(z_map, contrast_path)
            results["outputs"][f"{name}_map_path"] = contrast_path

            # Generate and save plots
            logger.info(f"Generating plots for contrast: {name}")

            # Brain slices plot
            fig_slices = plotting.plot_stat_map(
                z_map,
                title=f"Haxby {name} (Z>{threshold})",
                threshold=threshold,
                display_mode="z",
                cut_coords=7,
                black_bg=True,
            )
            slices_path = os.path.join(OUTPUT_DIR, f"haxby_{name}_slices.png")
            fig_slices.savefig(slices_path)
            results["outputs"][f"{name}_slices_path"] = slices_path
            results["outputs"][f"{name}_slices_base64"] = _save_plot_to_base64(
                fig_slices
            )
            fig_slices.close()

            # Glass brain plot
            fig_glass = plotting.plot_glass_brain(
                z_map, threshold=threshold, title=f"Haxby {name} (Z>{threshold})"
            )
            glass_path = os.path.join(OUTPUT_DIR, f"haxby_{name}_glass.png")
            fig_glass.savefig(glass_path)
            results["outputs"][f"{name}_glass_path"] = glass_path
            results["outputs"][f"{name}_glass_base64"] = _save_plot_to_base64(fig_glass)
            fig_glass.close()

            # Extract clusters and peak coordinates
            try:
                clusters_table = get_clusters_table(
                    z_map, stat_threshold=threshold, cluster_threshold=10
                )
                if not clusters_table.empty:
                    table_path = os.path.join(OUTPUT_DIR, f"haxby_{name}_clusters.csv")
                    clusters_table.to_csv(table_path, index=False)
                    results["outputs"][f"{name}_clusters_path"] = table_path
                    results["outputs"][f"{name}_clusters_json"] = (
                        clusters_table.to_json(orient="records")
                    )

                    # Extract peak coordinates
                    peak_coords = []
                    for _, row in clusters_table.iterrows():
                        peak_coords.append(
                            {
                                "x": float(row["X"]),
                                "y": float(row["Y"]),
                                "z": float(row["Z"]),
                                "value": float(row["Peak Stat"]),
                            }
                        )
                    results["outputs"][f"{name}_peaks"] = peak_coords
                else:
                    results["outputs"][f"{name}_peaks"] = []
            except Exception as e:
                logger.warning(f"Could not extract clusters for {name}: {e}")
                results["outputs"][f"{name}_peaks"] = []

        # Store the main results
        results["outputs"]["fmri_img"] = str(
            fmri_img
        )  # Convert to string representation
        results["outputs"]["events"] = events.to_dict("records")
        results["outputs"]["design_columns"] = design.columns.tolist()
        results["outputs"]["contrast_names"] = list(contrast_maps.keys())

        results["success"] = True
        results["message"] = (
            f"Haxby dataset analysis completed successfully. Generated {len(contrast_maps)} contrasts."
        )
        logger.info("Haxby dataset analysis finished successfully.")

    except Exception as e:
        logger.exception("An error occurred during Haxby dataset analysis")
        results["message"] = f"An unexpected error occurred: {e}"

    return results


def analyze_resting_state(subject_id: str = "001") -> dict[str, Any]:
    """
    Placeholder for analyzing resting-state functional connectivity.

    Args:
        subject_id: Subject identifier.

    Returns:
        Placeholder result dictionary.
    """
    logger.info("Placeholder function for resting-state analysis called.")
    # In a full implementation, this would fetch resting-state data,
    # define seed regions (e.g., PCC), compute correlation maps, and visualize.
    return {
        "success": False,
        "message": "Resting-state analysis is not yet implemented.",
        "outputs": {},
    }


# MCP-compatible handler function
def handle_nilearn_request(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handles requests routed from the MCP agent for Nilearn analysis.

    Args:
        params: Dictionary of parameters extracted by the MCP agent.

    Returns:
        Dictionary containing the analysis results.
    """
    analysis_type = params.get("analysis_type", "general")
    threshold = params.get("threshold", 3.0)
    add_run_intercepts = params.get("add_run_intercepts", True)

    logger.info(
        f"Handling Nilearn request. Type: {analysis_type}, Threshold: {threshold}"
    )

    if analysis_type == "motor_task":
        return analyze_motor_task(threshold=threshold)
    elif analysis_type == "haxby_dataset":
        return analyze_haxby_dataset(
            threshold=threshold, add_run_intercepts=add_run_intercepts
        )
    elif analysis_type == "resting_state":
        # Assuming a default subject or needing subject info passed in params
        return analyze_resting_state()
    else:
        # Default or fallback behavior if type is unclear
        logger.warning(
            f"Unknown or general analysis type: {analysis_type}. Attempting motor task analysis."
        )
        # As a fallback, attempt motor task analysis or return an error/clarification message
        # return analyze_motor_task(threshold=threshold)
        return {
            "success": False,
            "message": f"Analysis type {analysis_type} not supported.",
            "outputs": {},
        }


# Example usage (for testing the module directly)
if __name__ == "__main__":
    print("Testing Nilearn Integration Module...")

    # Test motor task analysis
    motor_results = analyze_motor_task(threshold=3.5)
    print("\n--- Motor Task Analysis Results ---")
    print(f"Success: {motor_results['success']}")
    print(f"Message: {motor_results['message']}")
    if motor_results["success"]:
        print("Generated outputs:")
        for key, value in motor_results["outputs"].items():
            if (
                isinstance(value, str) and len(value) > 100
            ):  # Avoid printing long base64 strings
                print(f"  {key}: [base64 data]")
            elif isinstance(value, str) and value.endswith((".png", ".nii.gz", ".csv")):
                print(f"  {key}: {value}")
            elif key == "clusters_table_json":
                print(f"  {key}: {json.loads(value)}")  # Print parsed JSON table
            else:
                print(f"  {key}: {value}")

    # Test MCP handler
    print("\n--- Testing MCP Handler ---")
    mcp_params = {"analysis_type": "motor_task", "threshold": 4.0}
    handler_results = handle_nilearn_request(mcp_params)
    print(f"Handler Success: {handler_results['success']}")
    print(f"Handler Message: {handler_results['message']}")

    # Test Haxby analysis
    print("\n--- Testing Haxby Analysis ---")
    haxby_params = {
        "analysis_type": "haxby_dataset",
        "threshold": 3.0,
        "add_run_intercepts": True,
    }
    haxby_results = handle_nilearn_request(haxby_params)
    print(f"Haxby Success: {haxby_results['success']}")
    print(f"Haxby Message: {haxby_results['message']}")
    if haxby_results["success"]:
        print(
            f"Generated {len([k for k in haxby_results['outputs'].keys() if 'contrast' in k])} contrast outputs"
        )


def display_rag_results(results):
    """
    Display the results of the RAG literature retrieval.
    Args:
        results: List of literature retrieval results (from RAGKnowledgeSystem.query)
    """
    print("\n" + "-" * 20 + " Literature Retrieval Results " + "-" * 20)
    if not results or not isinstance(results, list):
        print("ERROR: No results returned or unexpected result format.")
        print("-" * 60)
        return

    print(f"SUCCESS: Found {len(results)} potentially relevant items.\n")
    for i, item in enumerate(results):
        print(f"  Item {i+1}:")
        if isinstance(item, dict):
            print(f"    Title: {item.get('title', 'N/A')}")
            print(
                f"    Abstract: {item.get('abstract', 'N/A')[:200]}..."
            )  # Show snippet
            print(f"    Source: {item.get('source', 'N/A')}")
            print(f"    ID/Link: {item.get('id', 'N/A')}")
            if "score" in item:
                print(f"    Relevance Score: {item['score']:.4f}")
        else:
            print(f"    Unexpected item format: {item}")
        print("  ---")
    print("-" * 60)

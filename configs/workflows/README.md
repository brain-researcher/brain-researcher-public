# Cognitive Encoding Model Workflow

## 1. Overview

This workflow implements a cognitive encoding model that learns a mapping from cognitive construct vectors (derived from task contrast definitions) to brain activation vectors (derived from fMRI contrast z-maps). The goal is to predict brain activation patterns based on cognitive features.

The workflow is defined in `encoding_model.yaml` and utilizes a series of Python scripts located in `/home/ubuntu/mri_assistant/tools/encoding_model_tools/`.

## 2. Workflow Steps (as defined in `encoding_model.yaml`)

The `encoding_model.yaml` file outlines the following conceptual steps:

1.  **Download BIDS Data**: Downloads necessary BIDS-formatted fMRI datasets (e.g., from OpenNeuro) using DataLad.
2.  **LLM-based Cognitive Annotation**: Generates cognitive feature vectors for each fMRI contrast using an LLM (or a predefined mapping) based on contrast descriptions and a list of cognitive constructs.
3.  **Brain Activation Parcellation**: Extracts mean activation values from contrast z-maps for predefined brain parcels using a brain atlas (e.g., Schaefer 2018).
4.  **Train Encoding Model**: Trains a regression model (e.g., Ridge Regression) to predict parcel-wise brain activations (Y) from cognitive feature vectors (X).
5.  **Evaluate Encoding Model**: Assesses the performance of the trained model using cross-validation and various metrics (e.g., R2 score, Pearson correlation).
6.  **Predict and Visualize Brain Maps**: Uses the trained model to predict brain activation maps for new cognitive construct vectors and visualizes these predictions.

## 3. Core Scripts and Their Functionality

The following Python scripts implement the core logic for each step:

### 3.1. `data_loader.py`

*   **Purpose**: Downloads BIDS datasets from specified OpenNeuro URLs using DataLad.
*   **Inputs**:
    *   `datasets_to_download`: A dictionary where keys are dataset IDs (e.g., "ds000001") and values are their OpenNeuro Git URLs.
    *   `download_location`: The base directory where datasets will be cloned.
    *   `get_small_subset`: Boolean, if true, attempts to download only a small subset of files (currently illustrative, full download instructions provided).
*   **Outputs**:
    *   Cloned DataLad datasets in the specified `download_location`.
    *   A JSON file (`download_summary.json`) summarizing the download status and paths.
*   **Usage Note**: After cloning, actual file contents need to be retrieved using `datalad get`. For example, to get specific files:
    ```bash
    cd /path/to/download_location/ds000001
    datalad get sub-01/anat/sub-01_T1w.nii.gz path/to/another/file.json
    ```
    To download all data for a dataset (this can be very large and time-consuming):
    ```bash
    cd /path/to/download_location/ds000001
    datalad get .
    ```

### 3.2. `cognitive_annotator.py`

*   **Purpose**: Generates a feature matrix (X) of cognitive vectors for fMRI contrasts. It reads BIDS-compliant statistical model JSON files (`*_smdl.json`), extracts contrast definitions, and uses an LLM (or a mock/dummy implementation if `DEEPSEEK_API_KEY` is not set) to assign binary (0 or 1) values for each predefined cognitive construct.
*   **Inputs**:
    *   `contrast_definition_files_pattern`: Glob pattern to find BIDS statistical model JSON files (e.g., `data/raw_bids/ds000001/models/model-*_smdl.json`).
    *   `cognitive_constructs_json_path`: Path to a JSON file defining the cognitive constructs and their descriptions (e.g., `knowledge/constructs.json`).
    *   `output_cognitive_feature_matrix_X_path`: Path to save the resulting NumPy array (n_contrasts x n_constructs).
    *   `output_contrast_to_vector_mapping_path`: Path to save a JSON file mapping contrast identifiers to their row index in the feature matrix and their original file.
    *   `project_root`: Base directory for resolving relative paths.
    *   `deepseek_api_key`: (Optional) API key for the DeepSeek LLM. If not provided, a dummy LLM response is used.
*   **Outputs**:
    *   `cognitive_vectors_X.npy`: The cognitive feature matrix.
    *   `contrast_map.json`: The mapping file.

### 3.3. `parcellation_util.py`

*   **Purpose**: Extracts brain activation signals from a set of contrast z-maps based on a specified brain atlas, creating a brain activation matrix (Y).
*   **Inputs**:
    *   `contrast_zmaps_pattern`: Glob pattern to find contrast z-map NIfTI files (e.g., `data/derivatives/fitlins/ds000001/results/contrast_estimates/*_zmap.nii.gz`). **These must be valid NIfTI files (e.g., `.nii.gz`).**
    *   `output_activation_matrix_Y_path`: Path to save the resulting NumPy array (n_contrasts x n_parcels).
    *   `output_parcel_labels_path`: Path to save a JSON file containing atlas information and the order of z-map files processed.
    *   `project_root`: Base directory for resolving relative paths.
    *   `atlas_name`: Name of the atlas to use (e.g., "Schaefer2018").
    *   `n_parcels`: Number of parcels for the chosen atlas (e.g., 100, 200, 400 for Schaefer2018).
    *   `network_variant`: Specific network variant of the atlas (e.g., "7Networks" or "17Networks" for Schaefer2018).
    *   `resolution_mm`: Resolution of the atlas in mm (e.g., 1 or 2).
*   **Outputs**:
    *   `brain_activation_vectors_Y.npy`: The brain activation matrix.
    *   `parcel_labels.json`: Atlas and file order information.

### 3.4. `model_trainer.py`

*   **Purpose**: Trains a RidgeCV (Ridge Regression with built-in cross-validation for alpha selection) model to predict brain activation vectors (Y) from cognitive vectors (X).
*   **Inputs**:
    *   `cognitive_vectors_X_path`: Path to the cognitive feature matrix X (.npy).
    *   `brain_activation_vectors_Y_path`: Path to the brain activation matrix Y (.npy).
    *   `output_trained_model_path`: Path to save the trained scikit-learn model (pickle file).
    *   `output_cross_val_scores_path`: Path to save a JSON file with cross-validation R2 scores.
    *   `project_root`: Base directory for resolving relative paths.
    *   `cv_folds`: Number of folds for cross-validation.
    *   `alphas`: List of alpha values for RidgeCV to try.
*   **Outputs**:
    *   `encoding_model.pkl`: The trained model pipeline.
    *   `model_cv_scores.json`: Cross-validation performance scores.

### 3.5. `model_evaluator.py`

*   **Purpose**: Evaluates the trained encoding model using various metrics on the full dataset and reports cross-validation scores from training.
*   **Inputs**:
    *   `trained_model_path`: Path to the trained model (.pkl).
    *   `cognitive_vectors_X_path`: Path to the full cognitive feature matrix X (.npy).
    *   `brain_activation_vectors_Y_path`: Path to the full brain activation matrix Y (.npy).
    *   `cross_val_scores_path`: Path to the JSON file with CV scores from training.
    *   `output_evaluation_report_path`: Path to save a Markdown evaluation report.
    *   `output_parcelwise_performance_path`: Path to save a CSV file with parcel-wise performance metrics.
    *   `project_root`: Base directory for resolving relative paths.
*   **Outputs**:
    *   `evaluation_report.md`: Markdown report summarizing model performance.
    *   `parcel_performance.csv`: CSV file with detailed parcel-wise metrics.

### 3.6. `model_visualizer.py`

*   **Purpose**: Uses the trained model to predict brain activation maps from new (or existing) cognitive construct vectors and visualizes these maps.
*   **Inputs**:
    *   `trained_model_path`: Path to the trained model (.pkl).
    *   `input_cognitive_constructs_path`: Path to a NumPy array (.npy) of cognitive vectors for which to predict brain maps.
    *   `parcel_labels_path`: Path to the JSON file from the parcellation step (contains atlas info).
    *   `output_predicted_brain_maps_dir`: Directory to save predicted brain maps as NIfTI files.
    *   `output_visualizations_dir`: Directory to save visualizations (e.g., PNG images).
    *   `project_root`: Base directory for resolving relative paths.
    *   `visualization_type`: Type of nilearn plot (e.g., "surface", "glass_brain").
*   **Outputs**:
    *   NIfTI files of predicted brain maps in `output_predicted_brain_maps_dir`.
    *   Image files of visualizations in `output_visualizations_dir`.

## 4. Data Requirements and Configuration

*   **BIDS Datasets**: Raw fMRI data should be in BIDS format. The `data_loader.py` script is designed for OpenNeuro datasets.
*   **Statistical Model Files**: `cognitive_annotator.py` expects BIDS-compliant statistical model definition files (e.g., `task-stopsignal_smdl.json`) that describe contrasts.
*   **Cognitive Constructs**: A JSON file (e.g., `knowledge/constructs.json`) is needed to define the set of cognitive constructs and their descriptions for the LLM annotation step. Example format:
    ```json
    {
      "reward_anticipation": "The cognitive process of anticipating a reward.",
      "working_memory": "The ability to hold and manipulate information in mind.",
      ...
    }
    ```
*   **Contrast Z-maps**: `parcellation_util.py` requires contrast z-maps as input. These **must be valid NIfTI files** (typically `.nii.gz`). Dummy files created with `touch` will not work and will cause errors during loading by `nibabel` or `nilearn`.
*   **Environment Variables**: For actual LLM-based annotation, the `DEEPSEEK_API_KEY` environment variable should be set. If not set, `cognitive_annotator.py` falls back to a mock/dummy annotation mechanism.

## 5. Running the Workflow (Example based on Validation Run)

A typical workflow execution would involve running these scripts sequentially. The validation run (`/home/ubuntu/mri_assistant_validation_run/`) provides a template for directory structure.

1.  **Setup Directories**: Create a project directory (e.g., `mri_assistant_validation_run`) with subdirectories for `data/raw_bids`, `data/derivatives/fitlins/.../contrast_estimates`, `data/processed`, `data/example_inputs`, `models`, `results`, `knowledge`.
2.  **Prepare `constructs.json`**: Place your `constructs.json` in the `knowledge` directory.
3.  **Run `data_loader.py`**: To download BIDS data.
    ```bash
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/data_loader.py
    # Then, cd into the downloaded dataset and use 'datalad get' for actual files.
    ```
4.  **Prepare BIDS model files (`*_smdl.json`)**: Place them in the appropriate BIDS model directory (e.g., `data/raw_bids/ds000001/models/`).
5.  **Run `cognitive_annotator.py`**: To generate cognitive vectors (X).
    ```bash
    # Ensure DEEPSEEK_API_KEY is set if using real LLM
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/cognitive_annotator.py
    ```
6.  **Prepare Contrast Z-maps**: Ensure valid NIfTI z-map files are present in the derivatives directory specified by the glob pattern for `parcellation_util.py`.
7.  **Run `parcellation_util.py`**: To generate brain activation vectors (Y).
    ```bash
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/parcellation_util.py
    ```
8.  **Run `model_trainer.py`**: To train the encoding model.
    ```bash
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/model_trainer.py
    ```
9.  **Run `model_evaluator.py`**: To evaluate the model.
    ```bash
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/model_evaluator.py
    ```
10. **Run `model_visualizer.py`**: To predict and visualize maps for new cognitive inputs (prepare an input .npy file for this step).
    ```bash
    python3.11 /home/ubuntu/mri_assistant/tools/encoding_model_tools/model_visualizer.py
    ```

Each script has an example `if __name__ == "__main__":` block that demonstrates its usage with dummy data and relative paths, assuming a specific project structure. These examples can be adapted for actual runs.

## 6. Full Data Download with DataLad

As mentioned in section 3.1, after `datalad clone`, the dataset directory contains metadata and pointers to files, but not the actual file content. To download all files within a cloned DataLad dataset (e.g., `ds000001` located in `/home/ubuntu/mri_assistant_validation_run/data/raw_bids_test/ds000001`):

```bash
cd /home/ubuntu/mri_assistant_validation_run/data/raw_bids_test/ds000001
datalad get .
```

**Warning**: This command will download **all** data for the dataset, which can be very large (many gigabytes or terabytes) and take a significant amount of time and disk space. It's often preferable to selectively download only the required files or subdirectories using `datalad get path/to/file_or_directory`.



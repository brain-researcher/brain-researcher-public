import argparse
import glob
import json
import os
import sys

import numpy as np
from nilearn import datasets
from nilearn.maskers import NiftiLabelsMasker
from sklearn.cross_decomposition import PLSRegression
from sklearn.decomposition import PCA, TruncatedSVD

sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "brain_researcher")
    ),
)
from brain_researcher.core.analysis.encoding_model_tools import model_trainer


def get_confidence_mask_from_annotations(annotations_json_path, threshold=0.3):
    with open(annotations_json_path) as f:
        annotations = json.load(f)
    constructs = annotations[0]["constructs"]
    confidences = np.array([c.get("llm_confidence", 1.0) for c in constructs])
    mask = confidences >= threshold
    return mask, confidences


parser = argparse.ArgumentParser(
    description="Parcellate z-stat maps and fit encoding model."
)
parser.add_argument(
    "--dataset",
    type=str,
    required=True,
    help="Dataset name, e.g. ds000001_balloon_analogue_risk_task or ALL for merged",
)
parser.add_argument(
    "--zmap_dir",
    type=str,
    help="Directory containing z-stat NIfTI files for this dataset (ignored if --dataset ALL)",
)
parser.add_argument(
    "--base_dir",
    type=str,
    default="llm_cogitive_function/data",
    help="Base data directory",
)
parser.add_argument(
    "--n_parcels",
    type=int,
    default=400,
    help="Number of parcels for Schaefer2018 atlas",
)
parser.add_argument(
    "--annotations_json_path",
    type=str,
    default=None,
    help="Path to annotations JSON for construct confidence filtering",
)
parser.add_argument(
    "--confidence_thresh",
    type=float,
    default=0.3,
    help="Confidence threshold for construct filtering",
)
parser.add_argument(
    "--x_reduce_method",
    type=str,
    default="none",
    choices=["none", "svd", "pls"],
    help="X reduction method",
)
parser.add_argument(
    "--x_n_components",
    type=float,
    default=None,
    help="Number of components for X reduction (int or float for variance)",
)
parser.add_argument(
    "--y_reduce_method",
    type=str,
    default="none",
    choices=["none", "pca"],
    help="Y reduction method",
)
parser.add_argument(
    "--y_n_components",
    type=float,
    default=None,
    help="Number of components for Y reduction (int or float for variance)",
)
parser.add_argument(
    "--preprocess_only",
    action="store_true",
    help="Only preprocess and save reduced X/Y, do not train model",
)
args = parser.parse_args()

base_dir = args.base_dir
dataset = args.dataset
n_parcels = args.n_parcels

if dataset == "ALL":
    vectors_dir = os.path.join(base_dir, "vectors")
    processed_dir = os.path.join(base_dir, "processed")
    all_X = []
    all_Y = []
    all_index = []
    for ds in sorted(os.listdir(vectors_dir)):
        x_path = os.path.join(vectors_dir, ds, "X.npy")
        index_path = os.path.join(vectors_dir, ds, "index.json")
        y_candidates = glob.glob(
            os.path.join(processed_dir, f"{ds}__task-*_Y_schaefer{n_parcels}.npy")
        )
        if not y_candidates:
            y_path = os.path.join(processed_dir, f"{ds}_Y_schaefer{n_parcels}.npy")
        else:
            y_path = y_candidates[0]
        if not (
            os.path.exists(x_path)
            and os.path.exists(index_path)
            and os.path.exists(y_path)
        ):
            print(f"Skipping {ds}: missing files.")
            continue
        X = np.load(x_path)
        Y = np.load(y_path)
        with open(index_path) as f:
            idx = json.load(f)
        if X.shape[0] != Y.shape[0] or X.shape[0] != len(idx):
            print(f"Skipping {ds}: shape mismatch.")
            continue
        all_X.append(X)
        all_Y.append(Y)
        all_index.extend([f"{ds}:{c}" for c in idx])
    if not all_X or not all_Y:
        raise RuntimeError("No datasets found for merging.")
    X_merged = np.vstack(all_X)
    Y_merged = np.vstack(all_Y)
    log_path = os.path.join(base_dir, "results/ALL_merge_info.log")
    with open(log_path, "w") as logf:
        logf.write(f"Merged X shape: {X_merged.shape}\n")
        logf.write(f"Merged Y shape: {Y_merged.shape}\n")
        logf.write(f"Total contrasts: {len(all_index)}\n")
        logf.write(
            f"Datasets included: {[ds for ds in sorted(os.listdir(vectors_dir)) if os.path.exists(os.path.join(vectors_dir, ds, 'X.npy'))]}\n"
        )
        logf.write(f"all_index (first 10): {all_index[:10]}\n")
    print(f"Merged X shape: {X_merged.shape}")
    print(f"Merged Y shape: {Y_merged.shape}")
    print(f"Total contrasts: {len(all_index)}")
    print(f"Log written to {log_path}")
    if args.annotations_json_path is not None:
        mask, confidences = get_confidence_mask_from_annotations(
            args.annotations_json_path, args.confidence_thresh
        )
        X_merged = X_merged[:, mask]
        print(
            f"Filtered X by confidence < {args.confidence_thresh}: {np.sum(~mask)} constructs dropped. New shape: {X_merged.shape}"
        )
    if args.x_reduce_method == "svd" and args.x_n_components is not None:
        svd = TruncatedSVD(
            n_components=(
                int(args.x_n_components)
                if args.x_n_components >= 1
                else args.x_n_components
            )
        )
        X_merged = svd.fit_transform(X_merged)
        print(f"X reduced by SVD to shape: {X_merged.shape}")
    elif args.x_reduce_method == "pls" and args.x_n_components is not None:
        pls = PLSRegression(n_components=int(args.x_n_components))
        X_merged = pls.fit_transform(X_merged, Y_merged)[0]
        print(f"X reduced by PLS to shape: {X_merged.shape}")
    if args.y_reduce_method == "pca" and args.y_n_components is not None:
        pca = PCA(n_components=args.y_n_components)
        Y_merged = pca.fit_transform(Y_merged)
        print(f"Y reduced by PCA to shape: {Y_merged.shape}")
    model_path = os.path.join(base_dir, "models/ALL_encoding_model.pkl")
    cv_path = os.path.join(base_dir, "results/ALL_model_cv_scores.json")
    n_samples = X_merged.shape[0]
    cv_folds = min(5, n_samples)
    if cv_folds < 2:
        print(f"Not enough samples ({n_samples}) for cross-validation. Skipping ALL.")
        sys.exit(0)
    results = model_trainer.train_ridge_model(
        cognitive_vectors_X_path=X_merged,
        brain_activation_vectors_Y_path=Y_merged,
        output_trained_model_path=model_path,
        output_cross_val_scores_path=cv_path,
        cv_folds=cv_folds,
        alphas=[0.1, 1.0, 10.0, 100.0, 1000.0],
    )
    print("Encoding model training results:", results)
    sys.exit(0)

# Per-dataset logic
# Use only the part before '__' for vectors lookup
if "__" in dataset:
    dataset_for_vectors = dataset.split("__")[0]
else:
    dataset_for_vectors = dataset
x_path = os.path.join(base_dir, f"vectors/{dataset_for_vectors}/X.npy")
index_path = os.path.join(base_dir, f"vectors/{dataset_for_vectors}/index.json")
y_path = os.path.join(base_dir, f"processed/{dataset}_Y_schaefer{n_parcels}.npy")
parcel_labels_path = os.path.join(
    base_dir, f"processed/{dataset}_parcel_labels_schaefer{n_parcels}.json"
)
filtered_x_path = os.path.join(base_dir, f"processed/{dataset}_filtered_X.npy")
filtered_index_path = os.path.join(base_dir, f"processed/{dataset}_filtered_index.json")
model_path = os.path.join(base_dir, f"models/{dataset}_encoding_model.pkl")
cv_path = os.path.join(base_dir, f"results/{dataset}_model_cv_scores.json")

with open(index_path) as f:
    contrast_names = json.load(f)
X = np.load(x_path)

# --- Multi-task zmap search logic ---
ds_prefix = dataset_for_vectors.split("_")[0]
zstatmap_root = os.path.join(base_dir, "z_statmap", ds_prefix)
found_contrasts = []
found_zmap_files = []
found_x_rows = []
for i, cname in enumerate(contrast_names):
    found = False
    for task_dir in os.listdir(zstatmap_root):
        node_dir = os.path.join(zstatmap_root, task_dir, "node-dataLevel")
        zmap_file = os.path.join(node_dir, f"contrast-{cname}_stat-z_statmap.nii.gz")
        if os.path.exists(zmap_file):
            found_contrasts.append(cname)
            found_zmap_files.append(zmap_file)
            found_x_rows.append(i)
            break
if not found_contrasts:
    raise RuntimeError(f"No z-stat maps found for any contrast in {dataset}.")
# Filter X and index.json
X_filtered = X[found_x_rows, :]
with open(filtered_index_path, "w") as f:
    json.dump(found_contrasts, f, indent=2)
np.save(filtered_x_path, X_filtered)
print(f"Filtered X shape: {X_filtered.shape}, contrasts: {len(found_contrasts)}")

# Parcellate all found zmap files
atlas = datasets.fetch_atlas_schaefer_2018(
    n_rois=n_parcels, yeo_networks=7, resolution_mm=1
)
masker = NiftiLabelsMasker(labels_img=atlas.maps, standardize=False)
Y = []
for zmap_file in found_zmap_files:
    arr = masker.fit_transform(zmap_file)
    Y.append(arr[0])
    print(f"Parcellated {zmap_file}, shape: {arr.shape}")
Y = np.vstack(Y)
np.save(y_path, Y)
print(f"Saved Y.npy to {y_path}, shape: {Y.shape}")

labels = [l.decode("utf-8") if isinstance(l, bytes) else str(l) for l in atlas.labels]
with open(parcel_labels_path, "w") as f:
    json.dump(
        {
            "atlas_name": "Schaefer2018",
            "n_parcels": n_parcels,
            "labels": labels,
            "processed_zmap_files_order": found_zmap_files,
        },
        f,
        indent=2,
    )
print(f"Saved parcel labels to {parcel_labels_path}")

# --- X confidence filter ---
if args.annotations_json_path is not None:
    mask, confidences = get_confidence_mask_from_annotations(
        args.annotations_json_path, args.confidence_thresh
    )
    X = X[:, mask]
    print(
        f"Filtered X by confidence < {args.confidence_thresh}: {np.sum(~mask)} constructs dropped. New shape: {X.shape}"
    )
# --- X reduction ---
if args.x_reduce_method == "svd" and args.x_n_components is not None:
    svd = TruncatedSVD(
        n_components=(
            int(args.x_n_components)
            if args.x_n_components >= 1
            else args.x_n_components
        )
    )
    X = svd.fit_transform(X)
    print(f"X reduced by SVD to shape: {X.shape}")
elif args.x_reduce_method == "pls" and args.x_n_components is not None:
    pls = PLSRegression(n_components=int(args.x_n_components))
    X = pls.fit_transform(X, Y)[0]
    print(f"X reduced by PLS to shape: {X.shape}")
# --- Y reduction ---
if args.y_reduce_method == "pca" and args.y_n_components is not None:
    pca = PCA(n_components=args.y_n_components)
    Y = pca.fit_transform(Y)
    print(f"Y reduced by PCA to shape: {Y.shape}")

n_samples = X_filtered.shape[0]
cv_folds = min(5, n_samples)
if cv_folds < 2:
    print(f"Not enough samples ({n_samples}) for cross-validation. Skipping {dataset}.")
    sys.exit(0)

results = model_trainer.train_ridge_model(
    cognitive_vectors_X_path=X_filtered,
    brain_activation_vectors_Y_path=Y,
    output_trained_model_path=model_path,
    output_cross_val_scores_path=cv_path,
    cv_folds=cv_folds,
    alphas=[0.1, 1.0, 10.0, 100.0, 1000.0],
)
print("Encoding model training results:", results)

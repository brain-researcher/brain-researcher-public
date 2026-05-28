#!/usr/bin/env python3.11
"""Script to convert downloaded Neurosynth v7 data to a NiMARE Dataset object."""

import os
import logging
from nimare import io

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Define relative paths ---
# Assume this script is in project_root/scripts/convert_neurosynth.py
# Or that it's run from the project root and paths are relative to CWD.
# For robustness, let's define paths relative to the script's location if it's moved into the project.
# If the script is run from the project root, these relative paths will also work.

# Determine project root assuming the script is in a 'scripts' subdirectory of the project root
# If the script is run from the project root itself, this logic might need adjustment or paths can be simpler.
# For now, let's assume the script will be placed in `mri_assistant/scripts/`

# Get the directory of the current script
# script_dir = os.path.dirname(os.path.abspath(__file__))
# project_root = os.path.dirname(script_dir) # Assumes script is in a 'scripts' subdir

# Simpler approach: Define paths relative to the current working directory
# This requires the script to be run from the project root directory.
project_root = os.getcwd()  # Assumes script is run from project root

data_sub_dir = os.path.join("data", "neurosynth_nimare", "neurosynth_v7")
output_sub_dir = os.path.join("data", "neurosynth_nimare")

# Define paths for Neurosynth v7 data relative to project root
data_dir = os.path.join(project_root, data_sub_dir)
coords_file = os.path.join(data_dir, "data-neurosynth_version-7_coordinates.tsv.gz")
metadata_file = os.path.join(data_dir, "data-neurosynth_version-7_metadata.tsv.gz")
features_file = os.path.join(
    data_dir,
    "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz",
)
vocabulary_file = os.path.join(
    data_dir, "data-neurosynth_version-7_vocab-terms_vocabulary.txt"
)
output_file = os.path.join(project_root, output_sub_dir, "neurosynth_dataset_v7.pkl")

logger.info(f"Starting conversion of Neurosynth v7 data...")
logger.info(f"Project root (assumed): {project_root}")
logger.info(f"Coordinates file: {coords_file}")
logger.info(f"Metadata file: {metadata_file}")
logger.info(f"Features file: {features_file}")
logger.info(f"Vocabulary file: {vocabulary_file}")
logger.info(f"Output file: {output_file}")

# Check if input files exist
missing_files = []
for f in [coords_file, metadata_file, features_file, vocabulary_file]:
    if not os.path.exists(f):
        missing_files.append(f)

if missing_files:
    logger.error(f"Missing input files: {', '.join(missing_files)}")
    logger.error(
        f"Please ensure these files are in {os.path.abspath(data_dir)} and the script is run from the project root."
    )
    exit(1)

# Ensure output directory exists
output_dir_for_pkl = os.path.dirname(output_file)
if not os.path.exists(output_dir_for_pkl):
    try:
        os.makedirs(output_dir_for_pkl)
        logger.info(f"Created output directory: {output_dir_for_pkl}")
    except OSError as e:
        logger.error(f"Error creating output directory {output_dir_for_pkl}: {e}")
        exit(1)

try:
    annotations = {"features": features_file, "vocabulary": vocabulary_file}

    logger.info("Calling nimare.io.convert_neurosynth_to_dataset...")
    dataset = io.convert_neurosynth_to_dataset(
        coordinates_file=coords_file,
        metadata_file=metadata_file,
        annotations_files=annotations,
    )
    logger.info("Conversion successful. Dataset object created.")

    logger.info(f"Saving Dataset object to: {output_file}")
    dataset.save(output_file)
    logger.info(f"Neurosynth data successfully converted and saved to: {output_file}")

except Exception as e:
    logger.exception("Error converting Neurosynth data.")

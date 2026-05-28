#!/usr/bin/env python3.11
"""Script to download Neurosynth v0.7 data files."""

import os
import requests
import shutil
from tqdm import tqdm  # For progress bar, ensure it's in requirements or handle absence

# Define file URLs and target directory
# URLs are based on common locations for Neurosynth data, verify if these are current
# Typically from https://github.com/neurosynth/neurosynth-data/tree/master/data
# Or directly from neurosynth.org archives if available.
# Using a direct link to a specific commit on GitHub for stability.
BASE_URL = "https://raw.githubusercontent.com/neurosynth/neurosynth-data/d23309a279f18b600019b4773347000300700007/data/"

FILES_TO_DOWNLOAD = {
    "data-neurosynth_version-7_coordinates.tsv.gz": BASE_URL
    + "neurosynth_version-7_coordinates.tsv.gz",
    "data-neurosynth_version-7_metadata.tsv.gz": BASE_URL
    + "neurosynth_version-7_metadata.tsv.gz",
    "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz": BASE_URL
    + "neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz",
    "data-neurosynth_version-7_vocab-terms_vocabulary.txt": BASE_URL
    + "neurosynth_version-7_vocab-terms_vocabulary.txt",
}

# Project root is assumed to be the parent directory of this script's location if placed in mri_assistant/scripts
# Or adjust as needed if script is placed elsewhere.
# For this execution, let's assume the script will be run from the project root or that the path is relative to it.
TARGET_DIR = os.path.join("data", "neurosynth_nimare", "neurosynth_v7")


def download_file(url, target_path):
    """Downloads a file from a URL to a target path with a progress bar."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()  # Raise an exception for HTTP errors
        total_size = int(response.headers.get("content-length", 0))

        with (
            open(target_path, "wb") as f,
            tqdm(
                desc=os.path.basename(target_path),
                total=total_size,
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
            ) as bar,
        ):
            for chunk in response.iter_content(chunk_size=8192):
                size = f.write(chunk)
                bar.update(size)
        print(f"Successfully downloaded {os.path.basename(target_path)}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while downloading {url}: {e}")
        return False


def main():
    """Main function to create directory and download files."""
    print(f"Target directory for Neurosynth data: {os.path.abspath(TARGET_DIR)}")

    if not os.path.exists(TARGET_DIR):
        try:
            os.makedirs(TARGET_DIR)
            print(f"Created directory: {TARGET_DIR}")
        except OSError as e:
            print(f"Error creating directory {TARGET_DIR}: {e}")
            return

    all_successful = True
    for filename, url in FILES_TO_DOWNLOAD.items():
        target_file_path = os.path.join(TARGET_DIR, filename)
        if os.path.exists(target_file_path):
            print(f"File {filename} already exists. Skipping download.")
            continue
        print(f"Downloading {filename} from {url}...")
        if not download_file(url, target_file_path):
            all_successful = False
            print(
                f"Failed to download {filename}. Please check the URL or your network connection."
            )

    if all_successful:
        print(
            "\nAll Neurosynth v0.7 data files downloaded (or already existed) successfully."
        )
    else:
        print("\nSome files failed to download. Please review the errors above.")


if __name__ == "__main__":
    # Ensure tqdm is available or provide a fallback
    try:
        from tqdm import tqdm
    except ImportError:
        print("tqdm library not found. Progress bars will not be shown.")

        # Basic fallback for tqdm if not installed
        class tqdm:
            def __init__(self, *args, **kwargs):
                self.iterable = args[0] if args else None
                self.desc = kwargs.get("desc", "")
                print(f"Starting: {self.desc}")

            def __iter__(self):
                return iter(self.iterable)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                print(f"Finished: {self.desc}")
                return False

            def update(self, n=1):
                pass  # No progress update without tqdm

    main()

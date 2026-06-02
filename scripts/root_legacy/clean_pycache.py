#!/usr/bin/env python3
"""
Script to clean all .pyc files and __pycache__ directories recursively.
Usage: python clean_pycache.py [directory]
"""

import os
import sys
import shutil
from pathlib import Path

def clean_pycache(directory="."):
    """Clean all .pyc files and __pycache__ directories in the given directory."""
    directory = Path(directory).resolve()

    if not directory.exists():
        print(f"Error: Directory '{directory}' does not exist.")
        return

    pyc_files = 0
    pycache_dirs = 0

    # Find and remove .pyc files
    for pyc_file in directory.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            pyc_files += 1
            print(f"Removed: {pyc_file}")
        except Exception as e:
            print(f"Error removing {pyc_file}: {e}")

    # Find and remove __pycache__ directories
    for pycache_dir in directory.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir)
            pycache_dirs += 1
            print(f"Removed: {pycache_dir}")
        except Exception as e:
            print(f"Error removing {pycache_dir}: {e}")

    print(f"\nCleaning complete!")
    print(f"Removed {pyc_files} .pyc files")
    print(f"Removed {pycache_dirs} __pycache__ directories")

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    clean_pycache(target_dir)

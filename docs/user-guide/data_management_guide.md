# Data Management Guide

This guide explains how data is managed in the Brain Researcher project using Git LFS (Large File Storage).

## Overview

The Brain Researcher project uses Git LFS to efficiently manage large data files including:
- Neuroimaging files (NIfTI, MGZ)
- Model files (pickle, HDF5)
- Large datasets (CSV, JSON)

## Setup

### 1. Install Git LFS

```bash
# macOS
brew install git-lfs

# Ubuntu/Debian
sudo apt-get install git-lfs

# Windows
# Download from https://git-lfs.github.com/
```

### 2. Initialize Git LFS

```bash
git lfs install
```

### 3. Clone Repository with LFS

```bash
# Clone with all LFS files
git clone <repository-url>
cd brain_researcher
git lfs pull

# Or clone without LFS files initially
git clone <repository-url>
cd brain_researcher
git lfs pull --include="data/neurokg/db/*.db"  # Pull specific files
```

## File Types Tracked by LFS

The following file types are automatically tracked by Git LFS (defined in `.gitattributes`):

- **Neuroimaging**: `*.nii`, `*.nii.gz`, `*.mgz`, `*.mgh`
- **Models**: `*.pkl`, `*.h5`, `*.pt`, `*.pth`, `*.ckpt`
- **Data**: `*.npz`, `*.npy`, `*.mat`, `*.parquet`
- **Archives**: `*.tar.gz`, `*.zip`
- **Large JSONs**: Specific files like `pubmed_publications.json`

## Data Organization

```
data/
├── neurokg/          # Knowledge graph data
│   ├── raw/         # Raw data files (Git LFS for large files)
│   └── logs/        # Processing logs (not in Git)
├── templates/       # Brain templates (Git LFS)
├── examples/        # Example datasets
└── test_data/      # Test files
```

## Using the Data Download Script

The project includes a data management script:

```bash
# Check data status
python scripts/data/download_data.py check

# List available data sources
python scripts/data/download_data.py list-sources

# Download specific datasets
python scripts/data/download_data.py download neurosynth

# Set up data directories
python scripts/data/download_data.py setup
```

## Working with Large Files

### Adding New Large Files

```bash
# Track a new file type
git lfs track "*.newext"

# Track a specific large file
git lfs track "path/to/largefile.json"

# Add and commit
git add .gitattributes path/to/largefile.json
git commit -m "Add large file with LFS"
```

### Checking LFS Status

```bash
# Show LFS files in current commit
git lfs ls-files

# Show all LFS files
git lfs ls-files --all

# Check LFS storage usage
git lfs status
```

### Fetching Specific Files

```bash
# Fetch only specific files
git lfs fetch --include="data/neurokg/db/*.db"
git lfs checkout

# Exclude certain files
git lfs fetch --exclude="data/examples/*"
```

## Best Practices

1. **File Size Limits**
   - Keep individual files under 100MB when possible
   - Consider splitting very large datasets
   - Use compression for text data

2. **Data Privacy**
   - Never commit sensitive or personal data
   - Anonymize subject data
   - Use `.gitignore` for temporary files

3. **Performance**
   - Clone without LFS files for faster initial clone
   - Pull only needed LFS files
   - Use sparse checkout for large repositories

4. **Storage**
   - Monitor LFS bandwidth usage
   - Consider external storage for files >1GB
   - Keep backups of critical data

## Troubleshooting

### LFS Files Not Downloading
```bash
git lfs fetch --all
git lfs checkout
```

### Pointer Files Instead of Actual Files
```bash
git lfs pull
```

### Storage Quota Exceeded
- Check quota with hosting provider
- Remove old LFS objects: `git lfs prune`
- Consider moving very large files to external storage

### Slow Clone/Pull
```bash
# Clone without LFS files
GIT_LFS_SKIP_SMUDGE=1 git clone <repository-url>
# Then pull specific files as needed
git lfs pull --include="data/neurokg/db/*.db"
```

## Migration from Existing Data

If you have existing data files:

1. Ensure files are in `.gitignore`
2. Track with LFS: `git lfs track "*.ext"`
3. Add files: `git add --force data/myfile.ext`
4. Commit: `git commit -m "Migrate data to LFS"`

## External Data Sources

Some data is too large for Git LFS and should be downloaded separately:

- Large fMRI datasets: Use `openneuro-cli` or `datalad`
- NeuroVault collections: Use the NeuroVault API
- Full Neurosynth database: Download from official sources

Use the Brain Researcher CLI to manage these:
```bash
br data load-openneuro --dataset ds000001
br ingest neurovault <collection_id>
```

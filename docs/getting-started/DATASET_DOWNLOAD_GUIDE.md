# Brain Researcher - Dataset Download Guide

## Overview
This guide lists the essential datasets you should download to fully utilize the Brain Researcher system. The loaders now require real data files and will fail with clear error messages if data is not available.

---

## 1. 🧠 **OpenNeuro Datasets** (Public, Free)
**Loader**: `openneuro_unified.py`  
**Access**: https://openneuro.org  
**How to Download**: 
```bash
# Using OpenNeuro CLI
pip install openneuro-py
openneuro download --dataset ds000001 --target /data/openneuro/

# Or using the loader directly (when API is working)
from brain_researcher.core.ingestion.loaders.openneuro_unified import OpenNeuroUnifiedLoader
loader = OpenNeuroUnifiedLoader()
loader.download_dataset("ds000001")
```

### Recommended Starter Datasets:
- **ds000001**: Balloon Analog Risk Task (small, good for testing)
- **ds000030**: UCLA Consortium (comprehensive cognitive tasks)
- **ds000224**: Visual perception (MEG + MRI multimodal)
- **ds003604**: Naturalistic viewing (movie watching)
- **ds000117**: Multimodal (MEG/EEG/MRI) faces vs scrambled

---

## 2. 📊 **Human Connectome Project (HCP)**
**Loader**: `hcp_unified.py`  
**Access**: https://www.humanconnectome.org/  
**Requirements**: 
- Register for free account
- Download ConnectomeDB data

**Essential Files**:
```
/data/hcp/
├── HCP_1200_behavioral.csv  # Behavioral measures
├── HCP_1200_demographics.csv
└── subjects/
    ├── 100307/
    ├── 100408/
    └── ...
```

**Quick Start**:
```python
from brain_researcher.core.ingestion.loaders.hcp_unified import HCPUnifiedLoader
loader = HCPUnifiedLoader()
# Requires actual CSV files
behavioral = loader.load_behavioral_data("/data/hcp/HCP_1200_behavioral.csv")
```

---

## 3. 🧬 **ADNI (Alzheimer's Disease Neuroimaging Initiative)**
**Loader**: `adni_unified.py`  
**Access**: http://adni.loni.usc.edu/  
**Requirements**: 
- Apply for access (free for researchers)
- Download ADNIMERGE package

**Essential Files**:
```
/data/adni/
├── ADNIMERGE.csv           # Main merged dataset
├── UPENN_CSF_BIOMARKERS.csv
├── COGNITIVE_ASSESSMENTS.csv
└── MRI_VOLUMES.csv
```

---

## 4. 👶 **ABCD Study (Adolescent Brain Cognitive Development)**
**Loader**: `abcd_unified.py`  
**Access**: https://nda.nih.gov/abcd  
**Requirements**:
- NDA account and data use agreement
- Download Release 4.0 or later

**Essential Files**:
```
/data/abcd/
├── abcd_participants.tsv
├── abcd_ravlt01.txt        # Rey Auditory Verbal Learning
├── abcd_cbcls01.txt        # Child Behavior Checklist
└── abcd_imgincl01.txt      # Imaging inclusion
```

---

## 5. 🏛️ **CamCAN (Cambridge Centre for Ageing and Neuroscience)**
**Loader**: `camcan_unified.py`  
**Access**: https://www.cam-can.org/  
**Requirements**: Data sharing agreement

**Essential Files**:
```
/data/camcan/
├── participants.tsv
├── cognitive_measures.csv
└── lifestyle_data.csv
```

---

## 6. 🧓 **OASIS (Open Access Series of Imaging Studies)**
**Loader**: `oasis_unified.py`  
**Access**: https://www.oasis-brains.org/  
**Three datasets available:

### OASIS-1 (Cross-sectional)
```
/data/oasis/
├── oasis_cross-sectional.csv
```

### OASIS-2 (Longitudinal)
```
/data/oasis/
├── oasis_longitudinal.csv
```

### OASIS-3 (Comprehensive)
```
/data/oasis/
├── OASIS3_participants.csv
├── OASIS3_MR_sessions.csv
└── OASIS3_UDSv2.csv
```

---

## 7. 📚 **Literature & Ontologies** (Automatically Downloaded)

### PubMed
**Loader**: `pubmed_unified.py`  
**Access**: Automatic via API (no download needed)
```python
loader = PubMedUnifiedLoader()
papers = loader.search_papers("fMRI visual cortex", max_results=100)
```

### NeuroVault
**Loader**: `neurovault_unified.py`  
**Access**: Automatic via API
```python
loader = NeuroVaultUnifiedLoader()
collections = loader.get_collections(limit=50)
```

### Cognitive Atlas
**Loader**: `cognitive_atlas_unified.py`  
**Access**: Via API or NICLIP data

### NeuroSynth
**Loader**: `neurosynth_unified.py`  
**Download**: https://neurosynth.org/data/
```
/data/neurosynth/
├── database.txt
├── features.txt
└── coordinates.txt
```

---

## 8. 🤖 **NICLIP Pre-computed Data**
**Loader**: `niclip_embeddings.py`  
**Access**: Request from NICLIP team

Essential structure:
```
/data/niclip/
├── text/
│   ├── text-normalized_section-abstract_embedding-Llama-2-7b-chat-hf.npy
│   └── text-normalized_section-body_embedding-Mistral-7B-v0.1.npy
├── coordinates/
│   ├── coordinates-MKDA_embeddings.npy
│   └── coordinates-DiFuMo_embeddings.npy
└── data/
    └── cognitive_atlas/
        └── task_mappings.json
```

---

## Quick Start Script

Create a file `/data/download_datasets.sh`:

```bash
#!/bin/bash

# Create directory structure
mkdir -p /data/{openneuro,hcp,adni,abcd,camcan,oasis,neurosynth,niclip}

# Download small OpenNeuro dataset for testing
pip install openneuro-py
openneuro download --dataset ds000001 --target /data/openneuro/

# Download NeuroSynth database
cd /data/neurosynth
wget https://neurosynth.org/data/database.txt
wget https://neurosynth.org/data/features.txt

echo "Basic datasets downloaded. For full datasets, follow the guide above."
```

---

## Priority Order for Downloads

### 🚀 **Essential (Start Here)**
1. **OpenNeuro ds000001** - Small, quick test dataset
2. **NeuroSynth database** - Meta-analysis data
3. **PubMed** - No download needed (API access)

### 📈 **Recommended**
4. **HCP subset** - Download 10-20 subjects for testing
5. **OASIS-1** - Cross-sectional aging data
6. **Cognitive Atlas** - Task ontology

### 🔬 **Advanced**
7. **ABCD** - Large adolescent study
8. **ADNI** - Alzheimer's progression
9. **CamCAN** - Lifespan data
10. **NICLIP embeddings** - Pre-computed features

---

## Testing Your Downloads

After downloading, test each loader:

```python
from brain_researcher.core.ingestion.loaders import (
    openneuro_unified,
    hcp_unified,
    adni_unified,
    # ... etc
)

# Test OpenNeuro
on_loader = openneuro_unified.OpenNeuroUnifiedLoader()
datasets = on_loader.query_datasets(limit=5, demo_mode=False)  # Real data

# Test HCP
hcp_loader = hcp_unified.HCPUnifiedLoader()
subjects = hcp_loader.load_subject_list("/data/hcp/subjects.txt", demo_mode=False)

# Continue testing other loaders...
```

---

## Storage Requirements

### Minimum (Testing)
- **5-10 GB**: Sample datasets, small OpenNeuro studies

### Recommended
- **100-500 GB**: Multiple OpenNeuro datasets, HCP subset, OASIS

### Full Research
- **2-5 TB**: Complete HCP, ABCD, ADNI, multiple large studies

---

## Troubleshooting

### If a loader fails:
```python
# Check what file it needs
try:
    loader.load_data()
except ValueError as e:
    print(e)  # Will show required file path
```

### Use demo mode for testing without data:
```python
loader = HCPUnifiedLoader(demo_mode=True)
data = loader.load_behavioral_data(demo_mode=True)  # Returns sample data
```

---

## Important Notes

1. **No More Mock Data**: Loaders will fail if real data files are not found (unless `demo_mode=True`)
2. **Data Agreements**: Many datasets require registration and data use agreements
3. **Storage**: Plan for adequate storage, especially for imaging data
4. **Processing**: Some datasets require preprocessing (e.g., fMRIPrep for BIDS data)
5. **Updates**: Check dataset websites for latest versions

---

## Contact & Support

- OpenNeuro: support@openneuro.org
- HCP: hcp-users@humanconnectome.org
- ADNI: http://adni.loni.usc.edu/data-samples/access-data/
- ABCD: ABCDStudy@ucsd.edu

For Brain Researcher specific issues, check the documentation or raise an issue on GitHub.
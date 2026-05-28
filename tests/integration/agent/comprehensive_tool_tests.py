#!/usr/bin/env python3
"""
Comprehensive test cases for all Brain Researcher tools.
Each tool has 3-5 different test cases covering normal use, edge cases, and error conditions.
"""

import json
import requests
from datetime import datetime
from typing import Dict, List, Any

AGENT_URL = "http://localhost:8000"

# Define comprehensive test cases for each tool
COMPREHENSIVE_TOOL_TESTS = {
    # ==================== fMRI Analysis Tools ====================
    "glm_analysis": [
        {
            "name": "Basic motor task contrast",
            "args": {
                "dataset_id": "ds000001",
                "contrasts": {"motor_vs_baseline": [1, -1]}
            },
            "description": "Simple motor vs baseline contrast"
        },
        {
            "name": "Complex multi-contrast design",
            "args": {
                "dataset_id": "ds000030",
                "contrasts": {
                    "faces_vs_houses": [1, -1, 0, 0],
                    "faces_vs_baseline": [1, 0, 0, -1],
                    "houses_vs_baseline": [0, 1, 0, -1],
                    "main_effect": [1, 1, 0, -2]
                }
            },
            "description": "Multiple contrasts for visual experiment"
        },
        {
            "name": "Single contrast with custom threshold",
            "args": {
                "dataset_id": "ds000117",
                "contrasts": {"language_vs_control": [1, -1]},
                "threshold": 2.3
            },
            "description": "Language task with lower threshold"
        },
        {
            "name": "Invalid dataset ID",
            "args": {
                "dataset_id": "ds999999",
                "contrasts": {"test": [1, -1]}
            },
            "description": "Should handle non-existent dataset",
            "expect_error": True
        },
        {
            "name": "Missing contrasts",
            "args": {
                "dataset_id": "ds000001"
            },
            "description": "Should fail when contrasts not provided",
            "expect_error": True
        }
    ],
    
    "encoding_model": [
        {
            "name": "Visual encoding with default parcellation",
            "args": {
                "dataset_id": "ds000001",
                "parcellation": "schaefer_400"
            },
            "description": "Standard visual encoding model"
        },
        {
            "name": "Motor encoding with custom parcellation",
            "args": {
                "dataset_id": "ds000030",
                "parcellation": "glasser_360",
                "features": ["motor", "movement", "action"]
            },
            "description": "Motor features with Glasser parcellation"
        },
        {
            "name": "Multi-feature encoding model",
            "args": {
                "dataset_id": "ds000117",
                "parcellation": "schaefer_400",
                "features": ["phonemes", "words", "syntax"]
            },
            "description": "Language model with multiple features"
        },
        {
            "name": "Invalid parcellation",
            "args": {
                "dataset_id": "ds000001",
                "parcellation": "invalid_atlas"
            },
            "description": "Should handle unknown parcellation",
            "expect_error": True
        },
        {
            "name": "Memory-intensive dataset",
            "args": {
                "dataset_id": "ds003097",
                "parcellation": "schaefer_400"
            },
            "description": "Large dataset to test resource handling"
        }
    ],
    
    "contrast_analysis": [
        {
            "name": "Basic z-map analysis", 
            "args": {
                "z_map_path": "/data/glm/ds000001/pumps_zmap.nii.gz",
                "contrast_name": "pumps"
            },
            "description": "Standard contrast analysis - will use real data if available"
        },
        {
            "name": "Analysis with specific coordinates",
            "args": {
                "contrast_map": "/data/contrasts/faces_vs_houses_zmap.nii.gz",
                "threshold": 2.3,
                "coordinates": [[-42, -22, 54], [38, -86, -8], [0, -2, 48]]
            },
            "description": "Target specific brain regions"
        },
        {
            "name": "Multiple contrasts comparison",
            "args": {
                "contrast_map": "/data/contrasts/language_network_zmap.nii.gz",
                "threshold": 3.5,
                "atlas": "harvard_oxford"
            },
            "description": "Use specific atlas for labeling"
        },
        {
            "name": "Invalid file path",
            "args": {
                "contrast_map": "/nonexistent/path/contrast.nii.gz",
                "threshold": 3.1
            },
            "description": "Should handle missing files",
            "expect_error": True
        },
        {
            "name": "Low threshold edge case",
            "args": {
                "contrast_map": "/data/contrasts/weak_effect_zmap.nii.gz",
                "threshold": 1.0
            },
            "description": "Very low threshold for weak effects"
        }
    ],
    
    "brain_similarity": [
        {
            "name": "Same dataset correlation",
            "args": {
                "brain_map1": "/data/maps/subject01_task.nii.gz",
                "brain_map2": "/data/maps/subject02_task.nii.gz"
            },
            "description": "Compare subjects within dataset"
        },
        {
            "name": "Cross-dataset comparison",
            "args": {
                "brain_map1": "/data/ds000001/derivatives/contrast.nii.gz",
                "brain_map2": "/data/ds000030/derivatives/contrast.nii.gz",
                "metric": "correlation"
            },
            "description": "Compare across different studies"
        },
        {
            "name": "Different similarity metrics",
            "args": {
                "brain_map1": "/data/maps/encoding_model1.nii.gz",
                "brain_map2": "/data/maps/encoding_model2.nii.gz",
                "metric": "cosine"
            },
            "description": "Use cosine similarity"
        },
        {
            "name": "With custom brain mask",
            "args": {
                "brain_map1": "/data/maps/map1.nii.gz",
                "brain_map2": "/data/maps/map2.nii.gz",
                "mask": "/data/masks/visual_cortex_mask.nii.gz"
            },
            "description": "Restrict to specific brain region"
        },
        {
            "name": "Invalid maps",
            "args": {
                "brain_map1": "/invalid/map1.nii.gz",
                "brain_map2": "/invalid/map2.nii.gz"
            },
            "description": "Should handle missing files",
            "expect_error": True
        }
    ],
    
    # ==================== BR-KG Knowledge Graph Tools ====================
    "find_related_concepts": [
        {
            "name": "Basic concept search",
            "args": {
                "concept": "motor cortex",
                "depth": 2,
                "limit": 10
            },
            "description": "Find concepts related to motor cortex"
        },
        {
            "name": "Deep graph traversal",
            "args": {
                "concept": "working memory",
                "depth": 3,
                "limit": 20
            },
            "description": "Deeper search for working memory network"
        },
        {
            "name": "Limited results",
            "args": {
                "concept": "visual cortex",
                "depth": 1,
                "limit": 3
            },
            "description": "Get only top 3 directly connected concepts"
        },
        {
            "name": "Non-existent concept",
            "args": {
                "concept": "quantum_brain_interface",
                "depth": 2,
                "limit": 10
            },
            "description": "Should handle unknown concepts gracefully",
            "expect_error": True
        },
        {
            "name": "Special characters in concept",
            "args": {
                "concept": "pre-SMA (supplementary motor area)",
                "depth": 2,
                "limit": 5
            },
            "description": "Concept with parentheses and hyphens"
        }
    ],
    
    "coordinate_to_concept": [
        {
            "name": "Single coordinate lookup",
            "args": {
                "coordinates": [[-42, -22, 54]],
                "radius": 10
            },
            "description": "Map single MNI coordinate"
        },
        {
            "name": "Multiple coordinates batch",
            "args": {
                "coordinates": [
                    [-42, -22, 54],  # Left motor
                    [38, -86, -8],   # Right visual
                    [-45, 45, 0],    # Left IFG
                    [0, -2, 48]      # SMA
                ],
                "radius": 10
            },
            "description": "Batch process multiple regions"
        },
        {
            "name": "Custom radius search",
            "args": {
                "coordinates": [[25, -60, 60]],
                "radius": 15
            },
            "description": "Larger radius for broader search"
        },
        {
            "name": "Different top_k values",
            "args": {
                "coordinates": [[-30, -90, 0]],
                "radius": 10,
                "top_k": 3
            },
            "description": "Limit to top 3 concepts per coordinate"
        },
        {
            "name": "Invalid coordinates format",
            "args": {
                "coordinates": [-42, -22, 54],  # Not a list of lists
                "radius": 10
            },
            "description": "Should handle format errors",
            "expect_error": True
        }
    ],
    
    "concept_literature_search": [
        {
            "name": "Single concept search",
            "args": {
                "concept": "working memory",
                "limit": 10
            },
            "description": "Basic literature search"
        },
        {
            "name": "Multi-concept with keywords",
            "args": {
                "concept": "motor cortex",
                "keywords": ["fMRI", "TMS", "plasticity"],
                "limit": 15
            },
            "description": "Combine concept with keywords"
        },
        {
            "name": "Year-filtered search",
            "args": {
                "concept": "default mode network",
                "year_start": 2020,
                "year_end": 2024,
                "limit": 20
            },
            "description": "Recent papers only"
        },
        {
            "name": "Large result set",
            "args": {
                "concept": "attention",
                "limit": 100
            },
            "description": "Retrieve many papers"
        },
        {
            "name": "Empty concept",
            "args": {
                "concept": "",
                "limit": 10
            },
            "description": "Should handle empty search",
            "expect_error": True
        }
    ],
    
    "graph_query": [
        {
            "name": "Subgraph extraction",
            "args": {
                "query_type": "subgraph",
                "start_node": "motor cortex",
                "depth": 2
            },
            "description": "Extract subgraph around motor cortex"
        },
        {
            "name": "Path finding between nodes",
            "args": {
                "query_type": "path",
                "start_node": "visual cortex",
                "end_node": "motor cortex"
            },
            "description": "Find connection path between regions"
        },
        {
            "name": "Neighbor queries",
            "args": {
                "query_type": "neighbors",
                "start_node": "hippocampus"
            },
            "description": "Get direct neighbors only"
        },
        {
            "name": "With custom filters",
            "args": {
                "query_type": "subgraph",
                "start_node": "prefrontal cortex",
                "filters": {"relationship_type": "functional_connection"}
            },
            "description": "Filter by relationship type"
        },
        {
            "name": "Invalid query type",
            "args": {
                "query_type": "invalid_type",
                "start_node": "amygdala"
            },
            "description": "Should handle unknown query types",
            "expect_error": True
        }
    ],
    
    "task_to_concept_mapping": [
        {
            "name": "Common task mapping",
            "args": {
                "task_name": "n-back"
            },
            "description": "Map n-back task to concepts"
        },
        {
            "name": "Complex task name",
            "args": {
                "task_name": "stop signal task"
            },
            "description": "Multi-word task name"
        },
        {
            "name": "Without synonyms",
            "args": {
                "task_name": "finger tapping",
                "include_synonyms": False
            },
            "description": "Exact match only"
        },
        {
            "name": "Motor task mapping",
            "args": {
                "task_name": "motor sequence learning"
            },
            "description": "Complex motor task"
        },
        {
            "name": "Unknown task",
            "args": {
                "task_name": "quantum_meditation_task"
            },
            "description": "Should handle unknown tasks gracefully"
        }
    ],
    
    # ==================== Data Archive Tools ====================
    "openneuro_download": [
        {
            "name": "Small dataset download",
            "args": {
                "dataset_id": "ds000001",
                "download_dir": "/tmp/openneuro/ds000001"
            },
            "description": "Download small test dataset"
        },
        {
            "name": "Specific version download",
            "args": {
                "dataset_id": "ds000030",
                "version": "1.0.0",
                "download_dir": "/tmp/openneuro/ds000030_v1"
            },
            "description": "Download specific dataset version"
        },
        {
            "name": "Latest version",
            "args": {
                "dataset_id": "ds000117",
                "download_dir": "/tmp/openneuro/ds000117_latest"
            },
            "description": "Download most recent version"
        },
        {
            "name": "Invalid dataset ID",
            "args": {
                "dataset_id": "ds999999",
                "download_dir": "/tmp/openneuro/invalid"
            },
            "description": "Should handle non-existent dataset",
            "expect_error": True
        },
        {
            "name": "Partial download",
            "args": {
                "dataset_id": "ds000001",
                "download_dir": "/tmp/openneuro/partial",
                "include": ["sub-01/*"]
            },
            "description": "Download only subject 01"
        }
    ],
    
    "openneuro_list_files": [
        {
            "name": "List all files",
            "args": {
                "dataset_id": "ds000001"
            },
            "description": "List all files in dataset"
        },
        {
            "name": "Filter by extension",
            "args": {
                "dataset_id": "ds000030",
                "extension": ".nii.gz"
            },
            "description": "List only nifti files"
        },
        {
            "name": "Specific subject files",
            "args": {
                "dataset_id": "ds000117",
                "subject": "01"
            },
            "description": "List files for subject 01"
        },
        {
            "name": "Empty dataset",
            "args": {
                "dataset_id": "ds000000"
            },
            "description": "Edge case: empty or minimal dataset"
        },
        {
            "name": "Access denied dataset",
            "args": {
                "dataset_id": "ds_private"
            },
            "description": "Should handle permission errors",
            "expect_error": True
        }
    ],
    
    "dandi_search": [
        {
            "name": "Species-based search",
            "args": {
                "search_term": "mouse",
                "limit": 10
            },
            "description": "Search for mouse datasets"
        },
        {
            "name": "Technique-based search",
            "args": {
                "search_term": "two-photon",
                "limit": 15
            },
            "description": "Search by imaging technique"
        },
        {
            "name": "Combined filters",
            "args": {
                "search_term": "calcium imaging",
                "species": "mouse",
                "limit": 20
            },
            "description": "Multiple search criteria"
        },
        {
            "name": "Empty search term",
            "args": {
                "search_term": "",
                "limit": 5
            },
            "description": "Should return recent datasets"
        },
        {
            "name": "Large result limit",
            "args": {
                "search_term": "neuron",
                "limit": 100
            },
            "description": "Test pagination handling"
        }
    ],
    
    "dandi_download": [
        {
            "name": "Basic dandiset download",
            "args": {
                "dandiset_id": "000003",
                "download_dir": "/tmp/dandi/000003"
            },
            "description": "Download small test dandiset"
        },
        {
            "name": "Specific version",
            "args": {
                "dandiset_id": "000006",
                "version": "draft",
                "download_dir": "/tmp/dandi/000006_draft"
            },
            "description": "Download draft version"
        },
        {
            "name": "With file filtering",
            "args": {
                "dandiset_id": "000009",
                "download_dir": "/tmp/dandi/000009_filtered",
                "files": ["sub-01/*"]
            },
            "description": "Download specific files only"
        },
        {
            "name": "Invalid dandiset ID",
            "args": {
                "dandiset_id": "999999",
                "download_dir": "/tmp/dandi/invalid"
            },
            "description": "Should handle non-existent dandiset",
            "expect_error": True
        },
        {
            "name": "Large dandiset partial",
            "args": {
                "dandiset_id": "000026",
                "download_dir": "/tmp/dandi/000026_partial",
                "max_size": "1GB"
            },
            "description": "Download with size limit"
        }
    ],
    
    # ==================== Neuroimaging Analysis Tools ====================
    "neurosynth_meta_analysis": [
        {
            "name": "Single term analysis",
            "args": {
                "term": "working memory",
                "threshold": 0.01
            },
            "description": "Basic meta-analysis"
        },
        {
            "name": "Multiple terms",
            "args": {
                "terms": ["attention", "executive"],
                "threshold": 0.001
            },
            "description": "Combined terms analysis"
        },
        {
            "name": "Custom threshold",
            "args": {
                "term": "motor",
                "threshold": 0.05
            },
            "description": "Less stringent threshold"
        },
        {
            "name": "Rare term",
            "args": {
                "term": "proprioception",
                "threshold": 0.01
            },
            "description": "Less common term"
        },
        {
            "name": "Invalid threshold",
            "args": {
                "term": "memory",
                "threshold": 2.0
            },
            "description": "Should handle invalid threshold",
            "expect_error": True
        }
    ],
    
    "neurosynth_search_terms": [
        {
            "name": "Partial term search",
            "args": {
                "search_query": "mem"
            },
            "description": "Search for memory-related terms"
        },
        {
            "name": "Exact match search",
            "args": {
                "search_query": "attention",
                "exact_match": True
            },
            "description": "Exact term matching"
        },
        {
            "name": "Common prefix search",
            "args": {
                "search_query": "visual"
            },
            "description": "Find all visual-related terms"
        },
        {
            "name": "Special characters",
            "args": {
                "search_query": "n-back"
            },
            "description": "Term with hyphen"
        },
        {
            "name": "Empty search",
            "args": {
                "search_query": ""
            },
            "description": "Should return all terms or error"
        }
    ],
    
    "neurosynth_visualize": [
        {
            "name": "Basic visualization",
            "args": {
                "term": "motor",
                "threshold": 0.01
            },
            "description": "Standard brain map visualization"
        },
        {
            "name": "Custom threshold visualization",
            "args": {
                "term": "language",
                "threshold": 0.001,
                "display_mode": "ortho"
            },
            "description": "Orthogonal view with strict threshold"
        },
        {
            "name": "Multiple overlays",
            "args": {
                "terms": ["visual", "attention"],
                "threshold": 0.01,
                "colormap": "hot"
            },
            "description": "Overlay multiple activation maps"
        },
        {
            "name": "High-resolution output",
            "args": {
                "term": "memory",
                "threshold": 0.01,
                "dpi": 300
            },
            "description": "High quality output"
        },
        {
            "name": "Invalid term",
            "args": {
                "term": "nonexistent_term",
                "threshold": 0.01
            },
            "description": "Should handle missing term",
            "expect_error": True
        }
    ],
    
    "neurovault_search_images": [
        {
            "name": "Task-based search",
            "args": {
                "search_term": "motor task",
                "limit": 10
            },
            "description": "Search for motor task images"
        },
        {
            "name": "Modality filtering",
            "args": {
                "search_term": "fMRI",
                "modality": "T-statistic",
                "limit": 15
            },
            "description": "Filter by image type"
        },
        {
            "name": "Large result set",
            "args": {
                "search_term": "brain",
                "limit": 50
            },
            "description": "Many results"
        },
        {
            "name": "Complex query",
            "args": {
                "search_term": "working memory n-back",
                "limit": 20
            },
            "description": "Multi-word search"
        },
        {
            "name": "No results query",
            "args": {
                "search_term": "xyz123nonexistent",
                "limit": 10
            },
            "description": "Should return empty results"
        }
    ],
    
    "neurovault_download_collection": [
        {
            "name": "Public collection",
            "args": {
                "collection_id": 1952
            },
            "description": "Download public collection"
        },
        {
            "name": "Large collection",
            "args": {
                "collection_id": 2040,
                "max_images": 10
            },
            "description": "Limit number of images"
        },
        {
            "name": "With metadata",
            "args": {
                "collection_id": 3324,
                "include_metadata": True
            },
            "description": "Download with full metadata"
        },
        {
            "name": "Private collection",
            "args": {
                "collection_id": 99999
            },
            "description": "Should handle access errors",
            "expect_error": True
        },
        {
            "name": "Non-existent collection",
            "args": {
                "collection_id": -1
            },
            "description": "Should handle missing collection",
            "expect_error": True
        }
    ],
    
    # ==================== BIDS Tools ====================
    "validate_bids": [
        {
            "name": "Valid BIDS dataset",
            "args": {
                "bids_dir": "/data/bids/ds000001"
            },
            "description": "Validate clean BIDS dataset"
        },
        {
            "name": "Dataset with warnings",
            "args": {
                "bids_dir": "/data/bids/ds_with_warnings",
                "strict": False
            },
            "description": "Allow warnings"
        },
        {
            "name": "Invalid structure",
            "args": {
                "bids_dir": "/data/raw/unorganized"
            },
            "description": "Non-BIDS organized data"
        },
        {
            "name": "Missing required files",
            "args": {
                "bids_dir": "/data/bids/incomplete"
            },
            "description": "Missing dataset_description.json"
        },
        {
            "name": "Empty directory",
            "args": {
                "bids_dir": "/tmp/empty_dir"
            },
            "description": "Edge case: empty directory",
            "expect_error": True
        }
    ],
    
    "query_bids_layout": [
        {
            "name": "Query BOLD files",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "query": {"suffix": "bold", "extension": "nii.gz"}
            },
            "description": "Find all BOLD images"
        },
        {
            "name": "Subject-specific query",
            "args": {
                "bids_dir": "/data/bids/ds000030",
                "query": {"subject": "01", "suffix": "bold"}
            },
            "description": "Get files for specific subject"
        },
        {
            "name": "Multi-modal query",
            "args": {
                "bids_dir": "/data/bids/ds000117",
                "query": {"suffix": ["bold", "T1w"], "extension": "nii.gz"}
            },
            "description": "Query multiple modalities"
        },
        {
            "name": "Complex filters",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "query": {
                    "subject": ["01", "02"],
                    "task": "motor",
                    "run": 1,
                    "suffix": "bold"
                }
            },
            "description": "Multiple filter criteria"
        },
        {
            "name": "Invalid query",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "query": {"invalid_key": "value"}
            },
            "description": "Should handle invalid query keys"
        }
    ],
    
    "heudiconv_convert": [
        {
            "name": "Basic conversion",
            "args": {
                "dicom_dir": "/data/dicoms/subject01",
                "output_dir": "/tmp/bids/sub-01",
                "heuristic": "default"
            },
            "description": "Standard DICOM to BIDS conversion"
        },
        {
            "name": "Custom heuristic",
            "args": {
                "dicom_dir": "/data/dicoms/subject02",
                "output_dir": "/tmp/bids/sub-02",
                "heuristic": "/config/custom_heuristic.py"
            },
            "description": "Use custom conversion rules"
        },
        {
            "name": "Multi-session data",
            "args": {
                "dicom_dir": "/data/dicoms/longitudinal",
                "output_dir": "/tmp/bids/longitudinal",
                "session": "01"
            },
            "description": "Convert specific session"
        },
        {
            "name": "Invalid DICOM path",
            "args": {
                "dicom_dir": "/nonexistent/dicoms",
                "output_dir": "/tmp/bids/error"
            },
            "description": "Should handle missing DICOMs",
            "expect_error": True
        },
        {
            "name": "Corrupted files",
            "args": {
                "dicom_dir": "/data/dicoms/corrupted",
                "output_dir": "/tmp/bids/corrupted",
                "skip_corrupted": True
            },
            "description": "Skip corrupted DICOM files"
        }
    ],
    
    # ==================== Pipeline Tools ====================
    "run_fmriprep": [
        {
            "name": "Single subject",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "output_dir": "/tmp/derivatives/fmriprep",
                "participant_label": "01"
            },
            "description": "Process one subject"
        },
        {
            "name": "Multiple subjects",
            "args": {
                "bids_dir": "/data/bids/ds000030",
                "output_dir": "/tmp/derivatives/fmriprep_multi",
                "participant_label": ["01", "02", "03"]
            },
            "description": "Process multiple subjects"
        },
        {
            "name": "Custom parameters",
            "args": {
                "bids_dir": "/data/bids/ds000117",
                "output_dir": "/tmp/derivatives/fmriprep_custom",
                "participant_label": "01",
                "skip_bids_validation": True,
                "output_spaces": ["MNI152NLin2009cAsym", "T1w"]
            },
            "description": "Custom preprocessing options"
        },
        {
            "name": "Resource constraints",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "output_dir": "/tmp/derivatives/fmriprep_lowmem",
                "participant_label": "01",
                "mem_mb": 8000,
                "nthreads": 4
            },
            "description": "Limited resources"
        },
        {
            "name": "Invalid BIDS",
            "args": {
                "bids_dir": "/data/raw/not_bids",
                "output_dir": "/tmp/derivatives/error"
            },
            "description": "Should fail on non-BIDS data",
            "expect_error": True
        }
    ],
    
    "run_mriqc": [
        {
            "name": "Participant level",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "output_dir": "/tmp/derivatives/mriqc",
                "analysis_level": "participant"
            },
            "description": "Individual QC metrics"
        },
        {
            "name": "Group level",
            "args": {
                "bids_dir": "/data/bids/ds000030",
                "output_dir": "/tmp/derivatives/mriqc_group",
                "analysis_level": "group"
            },
            "description": "Group QC summary"
        },
        {
            "name": "Custom parameters",
            "args": {
                "bids_dir": "/data/bids/ds000117",
                "output_dir": "/tmp/derivatives/mriqc_custom",
                "modalities": ["T1w", "bold"],
                "fd_thres": 0.5
            },
            "description": "Specific modalities and thresholds"
        },
        {
            "name": "Large dataset",
            "args": {
                "bids_dir": "/data/bids/large_study",
                "output_dir": "/tmp/derivatives/mriqc_large",
                "n_procs": 8,
                "mem_gb": 16
            },
            "description": "Parallel processing"
        },
        {
            "name": "Missing data",
            "args": {
                "bids_dir": "/data/bids/incomplete",
                "output_dir": "/tmp/derivatives/mriqc_incomplete"
            },
            "description": "Handle incomplete datasets"
        }
    ],
    
    "run_qsiprep": [
        {
            "name": "Basic preprocessing",
            "args": {
                "bids_dir": "/data/bids/ds_diffusion",
                "output_dir": "/tmp/derivatives/qsiprep",
                "participant_label": "01"
            },
            "description": "Standard diffusion preprocessing"
        },
        {
            "name": "Custom outputs",
            "args": {
                "bids_dir": "/data/bids/ds_diffusion",
                "output_dir": "/tmp/derivatives/qsiprep_custom",
                "participant_label": "02",
                "output_resolution": 1.5
            },
            "description": "Custom output resolution"
        },
        {
            "name": "Multi-shell data",
            "args": {
                "bids_dir": "/data/bids/multishell",
                "output_dir": "/tmp/derivatives/qsiprep_multishell",
                "hmc_model": "eddy"
            },
            "description": "Multi-shell diffusion data"
        },
        {
            "name": "Invalid diffusion data",
            "args": {
                "bids_dir": "/data/bids/no_diffusion",
                "output_dir": "/tmp/derivatives/qsiprep_error"
            },
            "description": "No diffusion data present",
            "expect_error": True
        },
        {
            "name": "Resource limits",
            "args": {
                "bids_dir": "/data/bids/ds_diffusion",
                "output_dir": "/tmp/derivatives/qsiprep_limited",
                "participant_label": "01",
                "nthreads": 2,
                "mem_mb": 4000
            },
            "description": "Limited computational resources"
        }
    ],
    
    # ==================== Electrophysiology Tools ====================
    "run_spike_sorting": [
        {
            "name": "Kilosort2 sorting",
            "args": {
                "recording_path": "/data/ephys/recording1.dat",
                "sorter": "kilosort2"
            },
            "description": "Use Kilosort2 algorithm"
        },
        {
            "name": "SpyKING CIRCUS sorting",
            "args": {
                "recording_path": "/data/ephys/recording2.dat",
                "sorter": "spykingcircus",
                "num_workers": 4
            },
            "description": "Parallel spike sorting"
        },
        {
            "name": "Custom parameters",
            "args": {
                "recording_path": "/data/ephys/recording3.dat",
                "sorter": "mountainsort4",
                "params": {"detect_threshold": 4.5, "freq_min": 300}
            },
            "description": "Custom sorting parameters"
        },
        {
            "name": "Multi-channel data",
            "args": {
                "recording_path": "/data/ephys/neuropixels.dat",
                "sorter": "kilosort2",
                "channel_groups": [[0, 31], [32, 63]]
            },
            "description": "Channel group sorting"
        },
        {
            "name": "Invalid format",
            "args": {
                "recording_path": "/data/ephys/invalid.txt",
                "sorter": "kilosort2"
            },
            "description": "Should handle wrong file format",
            "expect_error": True
        }
    ],
    
    "run_suite2p": [
        {
            "name": "Basic 2-photon analysis",
            "args": {
                "data_path": "/data/2photon/session1",
                "output_path": "/tmp/suite2p/session1"
            },
            "description": "Standard Suite2p processing"
        },
        {
            "name": "Multi-plane imaging",
            "args": {
                "data_path": "/data/2photon/multiplane",
                "output_path": "/tmp/suite2p/multiplane",
                "nplanes": 4
            },
            "description": "Multiple imaging planes"
        },
        {
            "name": "Custom ROI detection",
            "args": {
                "data_path": "/data/2photon/session2",
                "output_path": "/tmp/suite2p/custom_roi",
                "threshold_scaling": 0.8,
                "max_overlap": 0.8
            },
            "description": "Adjust ROI detection parameters"
        },
        {
            "name": "Large dataset",
            "args": {
                "data_path": "/data/2photon/large_session",
                "output_path": "/tmp/suite2p/large",
                "batch_size": 2000
            },
            "description": "Process in batches"
        },
        {
            "name": "Corrupted tiff",
            "args": {
                "data_path": "/data/2photon/corrupted",
                "output_path": "/tmp/suite2p/error"
            },
            "description": "Should handle corrupted data",
            "expect_error": True
        }
    ],
    
    # ==================== NWB Tools ====================
    "read_nwb": [
        {
            "name": "Basic file reading",
            "args": {
                "file_path": "/data/nwb/example_file.nwb",
                "data_type": "all"
            },
            "description": "Read entire NWB file"
        },
        {
            "name": "Specific data types",
            "args": {
                "file_path": "/data/nwb/ephys_data.nwb",
                "data_type": "timeseries"
            },
            "description": "Read only time series data"
        },
        {
            "name": "Large file handling",
            "args": {
                "file_path": "/data/nwb/large_recording.nwb",
                "data_type": "acquisition",
                "lazy_load": True
            },
            "description": "Lazy loading for large files"
        },
        {
            "name": "Corrupted file",
            "args": {
                "file_path": "/data/nwb/corrupted.nwb"
            },
            "description": "Should handle corrupted files",
            "expect_error": True
        },
        {
            "name": "Missing file",
            "args": {
                "file_path": "/data/nwb/nonexistent.nwb"
            },
            "description": "Should handle missing files",
            "expect_error": True
        }
    ],
    
    "write_nwb": [
        {
            "name": "Basic file writing",
            "args": {
                "output_path": "/tmp/nwb/basic_output.nwb",
                "metadata": {
                    "experimenter": "Test User",
                    "lab": "Test Lab",
                    "institution": "Test Institution"
                },
                "data": {"test_timeseries": [1, 2, 3, 4, 5]}
            },
            "description": "Create basic NWB file"
        },
        {
            "name": "Complex metadata",
            "args": {
                "output_path": "/tmp/nwb/complex_output.nwb",
                "metadata": {
                    "experimenter": ["User 1", "User 2"],
                    "lab": "Neuroscience Lab",
                    "experiment_description": "Complex experiment",
                    "session_id": "session_001"
                },
                "data": {
                    "electrode_data": {"channels": 32, "sampling_rate": 30000},
                    "behavior_data": {"tracking": "video"}
                }
            },
            "description": "Complex experiment metadata"
        },
        {
            "name": "Multi-modal data",
            "args": {
                "output_path": "/tmp/nwb/multimodal.nwb",
                "metadata": {"experimenter": "Test"},
                "data": {
                    "ephys": {"units": 100},
                    "imaging": {"roi_count": 500},
                    "behavior": {"trials": 50}
                }
            },
            "description": "Multiple data modalities"
        },
        {
            "name": "Invalid path",
            "args": {
                "output_path": "/invalid/path/output.nwb",
                "metadata": {"experimenter": "Test"},
                "data": {}
            },
            "description": "Should handle invalid paths",
            "expect_error": True
        },
        {
            "name": "Permissions issue",
            "args": {
                "output_path": "/root/protected.nwb",
                "metadata": {"experimenter": "Test"},
                "data": {}
            },
            "description": "Should handle permission errors",
            "expect_error": True
        }
    ],
    
    "inspect_nwb": [
        {
            "name": "Basic inspection",
            "args": {
                "file_path": "/data/nwb/example_file.nwb"
            },
            "description": "Get basic file information"
        },
        {
            "name": "Detailed metadata",
            "args": {
                "file_path": "/data/nwb/complex_experiment.nwb",
                "detailed": True
            },
            "description": "Full metadata inspection"
        },
        {
            "name": "Data validation",
            "args": {
                "file_path": "/data/nwb/to_validate.nwb",
                "validate": True
            },
            "description": "Validate NWB compliance"
        },
        {
            "name": "Version checking",
            "args": {
                "file_path": "/data/nwb/old_version.nwb",
                "check_version": True
            },
            "description": "Check NWB schema version"
        },
        {
            "name": "Invalid NWB",
            "args": {
                "file_path": "/data/not_nwb/random_file.h5"
            },
            "description": "Non-NWB HDF5 file",
            "expect_error": True
        }
    ],
    
    # ==================== Quality Control Tools ====================
    "mriqc_group_report": [
        {
            "name": "Basic group report",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "output_dir": "/tmp/qc/mriqc_group"
            },
            "description": "Standard group QC report"
        },
        {
            "name": "Custom metrics",
            "args": {
                "bids_dir": "/data/bids/ds000030",
                "output_dir": "/tmp/qc/mriqc_custom",
                "metrics": ["fd_mean", "snr", "cnr"]
            },
            "description": "Select specific QC metrics"
        },
        {
            "name": "Large cohort",
            "args": {
                "bids_dir": "/data/bids/large_study",
                "output_dir": "/tmp/qc/mriqc_large",
                "n_jobs": 8
            },
            "description": "Parallel processing for large cohort"
        },
        {
            "name": "Missing participants",
            "args": {
                "bids_dir": "/data/bids/incomplete",
                "output_dir": "/tmp/qc/mriqc_incomplete",
                "skip_missing": True
            },
            "description": "Handle missing participant data"
        },
        {
            "name": "Invalid metrics",
            "args": {
                "bids_dir": "/data/bids/ds000001",
                "output_dir": "/tmp/qc/mriqc_error",
                "metrics": ["invalid_metric"]
            },
            "description": "Should handle unknown metrics",
            "expect_error": True
        }
    ],
    
    "visual_qc_launch": [
        {
            "name": "Functional QC",
            "args": {
                "data_dir": "/data/derivatives/fmriprep",
                "qc_type": "func"
            },
            "description": "QC functional data"
        },
        {
            "name": "Structural QC",
            "args": {
                "data_dir": "/data/derivatives/fmriprep",
                "qc_type": "anat"
            },
            "description": "QC anatomical data"
        },
        {
            "name": "Diffusion QC",
            "args": {
                "data_dir": "/data/derivatives/qsiprep",
                "qc_type": "dwi"
            },
            "description": "QC diffusion data"
        },
        {
            "name": "Custom parameters",
            "args": {
                "data_dir": "/data/derivatives/custom",
                "qc_type": "func",
                "outlier_threshold": 3.0,
                "n_cols": 5
            },
            "description": "Custom QC parameters"
        },
        {
            "name": "Invalid data type",
            "args": {
                "data_dir": "/data/derivatives/fmriprep",
                "qc_type": "invalid_type"
            },
            "description": "Should handle unknown QC type",
            "expect_error": True
        }
    ]
}


def test_tool(tool_name: str, test_case: Dict[str, Any]) -> Dict[str, Any]:
    """Test a single tool with given test case."""
    try:
        resp = requests.post(
            f"{AGENT_URL}/debug/tool/{tool_name}",
            json={"args": test_case["args"]},
            timeout=30
        )
        
        result = {
            "test_name": test_case["name"],
            "description": test_case["description"],
            "expect_error": test_case.get("expect_error", False),
            "status_code": resp.status_code,
        }
        
        if resp.status_code == 200:
            resp_data = resp.json()
            result["success"] = resp_data.get("success", False)
            result["has_data"] = bool(resp_data.get("result", {}).get("data"))
            result["error"] = resp_data.get("result", {}).get("error")
            
            # Check if result matches expectation
            if test_case.get("expect_error", False):
                result["passed"] = not result["success"]
            else:
                result["passed"] = result["success"]
        else:
            result["success"] = False
            result["passed"] = False
            result["error"] = f"HTTP {resp.status_code}"
            
    except requests.exceptions.Timeout:
        result = {
            "test_name": test_case["name"],
            "description": test_case["description"],
            "success": False,
            "passed": False,
            "error": "Request timeout"
        }
    except Exception as e:
        result = {
            "test_name": test_case["name"],
            "description": test_case["description"],
            "success": False,
            "passed": False,
            "error": str(e)
        }
    
    return result


def main():
    """Run comprehensive tests for all tools."""
    print(f"Starting comprehensive tool tests at {datetime.now()}")
    print("=" * 80)
    
    all_results = {}
    summary_stats = {
        "total_tools": 0,
        "total_tests": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "working_tools": set(),
        "partially_working_tools": set(),
        "broken_tools": set()
    }
    
    # Test each tool
    for tool_name, test_cases in COMPREHENSIVE_TOOL_TESTS.items():
        print(f"\n{'='*60}")
        print(f"Testing {tool_name}")
        print(f"{'='*60}")
        
        tool_results = []
        tool_passed = 0
        tool_total = len(test_cases)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[{i}/{tool_total}] {test_case['name']}")
            print(f"    {test_case['description']}")
            
            result = test_tool(tool_name, test_case)
            tool_results.append(result)
            
            if result["passed"]:
                print(f"    ✅ PASSED")
                tool_passed += 1
            else:
                print(f"    ❌ FAILED: {result.get('error', 'Unknown error')[:80]}...")
            
            summary_stats["total_tests"] += 1
            if result["passed"]:
                summary_stats["passed_tests"] += 1
            else:
                summary_stats["failed_tests"] += 1
        
        # Store results
        all_results[tool_name] = {
            "test_cases": tool_results,
            "passed": tool_passed,
            "total": tool_total,
            "success_rate": tool_passed / tool_total if tool_total > 0 else 0
        }
        
        # Categorize tool
        summary_stats["total_tools"] += 1
        if tool_passed == tool_total:
            summary_stats["working_tools"].add(tool_name)
        elif tool_passed > 0:
            summary_stats["partially_working_tools"].add(tool_name)
        else:
            summary_stats["broken_tools"].add(tool_name)
    
    # Print summary
    print("\n" + "=" * 80)
    print("COMPREHENSIVE TEST SUMMARY")
    print("=" * 80)
    
    print(f"\nOverall Statistics:")
    print(f"  Total Tools Tested: {summary_stats['total_tools']}")
    print(f"  Total Test Cases: {summary_stats['total_tests']}")
    print(f"  Passed Tests: {summary_stats['passed_tests']}")
    print(f"  Failed Tests: {summary_stats['failed_tests']}")
    print(f"  Success Rate: {summary_stats['passed_tests']/summary_stats['total_tests']*100:.1f}%")
    
    print(f"\n✅ FULLY WORKING TOOLS ({len(summary_stats['working_tools'])}):")
    for tool in sorted(summary_stats["working_tools"]):
        print(f"  - {tool} ({all_results[tool]['passed']}/{all_results[tool]['total']} tests passed)")
    
    print(f"\n⚠️  PARTIALLY WORKING TOOLS ({len(summary_stats['partially_working_tools'])}):")
    for tool in sorted(summary_stats["partially_working_tools"]):
        print(f"  - {tool} ({all_results[tool]['passed']}/{all_results[tool]['total']} tests passed)")
    
    print(f"\n❌ BROKEN TOOLS ({len(summary_stats['broken_tools'])}):")
    for tool in sorted(summary_stats["broken_tools"]):
        print(f"  - {tool} (0/{all_results[tool]['total']} tests passed)")
    
    # Save detailed results
    with open("comprehensive_test_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_tools": summary_stats["total_tools"],
                "total_tests": summary_stats["total_tests"],
                "passed_tests": summary_stats["passed_tests"],
                "failed_tests": summary_stats["failed_tests"],
                "working_tools": list(summary_stats["working_tools"]),
                "partially_working_tools": list(summary_stats["partially_working_tools"]),
                "broken_tools": list(summary_stats["broken_tools"])
            },
            "detailed_results": all_results
        }, f, indent=2)
    
    print(f"\nDetailed results saved to comprehensive_test_results.json")
    print(f"\nTest completed at {datetime.now()}")


if __name__ == "__main__":
    main()
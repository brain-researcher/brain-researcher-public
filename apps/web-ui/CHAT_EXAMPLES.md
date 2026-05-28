# Brain Researcher Chat Interface - Example Queries

Welcome to the Brain Researcher chat interface! Here are example queries you can try at **http://localhost:3000/studio/**

## 🧠 Basic Neuroimaging Analysis

```
Run GLM analysis on dataset ds000114 with motor task contrasts

Preprocess fMRI data in /data/bids/sub-01 using fMRIPrep

Extract brain using FSL BET from structural.nii.gz

Perform ICA decomposition on resting-state fMRI data

Apply spatial smoothing with 6mm FWHM to functional data

Coregister T1 and T2 images using ANTs

Segment brain tissue using FreeSurfer

Normalize images to MNI152 template
```

## 📊 Statistical Analysis

```
Compare activation between left and right motor cortex

Run group-level analysis on 20 subjects with mixed-effects model

Calculate contrast maps for faces vs houses task

Perform multiple comparison correction using FDR at q=0.05

Run paired t-test on pre and post intervention scans

Generate statistical parametric maps for language task

Compute effect sizes for group differences

Apply cluster-based thresholding at p<0.001
```

## 🔍 Knowledge Graph Queries

```
Find all studies about working memory in the frontal cortex

What brain regions are associated with language processing?

Show me publications about default mode network

List datasets with resting-state fMRI from OpenNeuro

Search for studies using the n-back task

Find papers about hippocampal volume in aging

Query NeuroVault for motor cortex activation maps

Get citations for studies on amygdala connectivity
```

## 🛠️ Tool-Specific Requests

```
List available FSL tools

Generate FreeSurfer recon-all command for T1 image

Setup CONN toolbox for functional connectivity analysis

Run MRIQC quality assessment on BIDS dataset

Create SPM batch script for preprocessing

Show me how to use FSL FEAT for task analysis

Generate QSIPrep command for diffusion preprocessing

Build fMRIPrep command with custom output spaces
```

## 🔬 Advanced Analyses

```
Perform seed-based connectivity analysis with PCC as seed

Run searchlight MVPA for object recognition task

Calculate fractional anisotropy from DTI data

Perform surface-based morphometry using FreeSurfer

Run dynamic connectivity analysis on resting-state data

Compute graph theory metrics for brain networks

Perform representational similarity analysis

Run psychophysiological interaction analysis
```

## 📈 Visualization Requests

```
Plot activation map on MNI template

Create glass brain visualization of significant clusters

Show connectivity matrix for default mode network

Generate QC report for preprocessed data

Create surface rendering of cortical thickness

Plot ROI time series from preprocessed data

Visualize tractography results

Generate motion parameter plots
```

## 💡 Complex Workflows

```
I have a BIDS dataset with 30 subjects doing a memory task. Run preprocessing with fMRIPrep, then GLM analysis with FSL FEAT, and finally group analysis

Extract hippocampal volumes from T1 images and correlate with behavioral scores

Compare resting-state networks between patients and controls using dual regression

Set up a complete pipeline for task-based fMRI including preprocessing, first-level, and group analysis

Process DTI data including eddy current correction, tensor fitting, and tractography

Run a voxel-based morphometry analysis comparing two groups

Perform a meta-analysis of motor cortex activation across multiple studies

Create a machine learning classifier to distinguish patient groups based on connectivity
```

## 🔧 Troubleshooting & Help

```
How do I fix slice timing issues in my fMRI data?

What's the best smoothing kernel for group analysis?

Explain the difference between FWE and FDR correction

Help me choose between FSL and SPM for my analysis

My registration failed, what should I check?

How do I handle subjects with different numbers of runs?

What's the recommended pipeline for pediatric data?

How can I improve the signal-to-noise ratio?
```

## 📝 Dataset Queries

```
Show me motor task datasets from OpenNeuro

Find studies with at least 50 participants

List available preprocessed datasets

What data is available for depression research?

Find datasets with both structural and functional MRI

Search for longitudinal aging studies

List datasets with diffusion imaging

Find open datasets for schizophrenia research
```

## 🤖 Testing Agent Capabilities

```
What tools do you have for diffusion MRI analysis?

Can you help me plan a study on visual perception?

Generate a complete analysis pipeline for task fMRI

What's your recommended workflow for VBM analysis?

List all available neuroimaging tools

What analyses can you perform on resting-state data?

Show me your connectivity analysis capabilities

What quality control metrics do you check?
```

## 🎯 Quick Test Queries

Start with these simple queries to test if everything is working:

```
hello

help

list tools

What can you do?

Show me an example analysis
```

## 📚 Educational Queries

```
Explain the GLM in fMRI analysis

What is independent component analysis?

Describe the preprocessing steps for fMRI

What are the advantages of surface-based analysis?

Explain motion correction strategies

What is the difference between functional and effective connectivity?

How does multiple comparison correction work?

What are the best practices for fMRI study design?
```

## 🔄 Data Management

```
Convert DICOM files to NIFTI format

Organize data into BIDS format

Validate my BIDS dataset

Create a data quality report

Check for missing files in dataset

Anonymize subject identifiers

Export results to standard formats

Generate a reproducible analysis script
```

## 🧬 Multimodal Integration

```
Combine fMRI and DTI results for joint analysis

Integrate PET and MRI data

Correlate EEG and fMRI signals

Merge structural and functional connectivity

Combine task and resting-state analyses

Link genetics data with imaging phenotypes

Integrate behavioral and brain measures

Combine MEG and fMRI for temporal-spatial analysis
```

## 💻 Command Generation

```
Generate a bash script for batch processing

Create a SLURM job submission script

Build a Docker command for reproducible analysis

Generate a Nipype workflow

Create a parallel processing script

Build a comprehensive QC pipeline

Generate commands for cloud processing

Create an automated analysis pipeline
```

---

## Usage Tips

1. **Start Simple**: Begin with "hello" or "list available tools" to ensure the system is responding
2. **Be Specific**: Include dataset IDs, file paths, or specific parameters when known
3. **Ask for Explanations**: The agent can explain concepts, methods, and best practices
4. **Request Commands**: Ask for specific command-line tools to be generated
5. **Iterate**: Based on responses, refine your queries for better results
6. **Use Natural Language**: The agent understands conversational queries
7. **Combine Operations**: You can ask for multi-step workflows in a single query

## Available Resources

- **160+ Neuroimaging Tools**: Including FSL, FreeSurfer, ANTs, SPM, AFNI, MRtrix, and more
- **Knowledge Graph**: Access to NeuroVault, OpenNeuro, PubMed, and other databases
- **Analysis Pipelines**: Pre-configured workflows for common analyses
- **Visualization Tools**: Multiple options for displaying results
- **Quality Control**: Automated QC metrics and reports

## Need Help?

If you encounter issues or need assistance:
- Type "help" for general guidance
- Ask "What can you do?" for capability overview
- Request "Show me an example" for demonstration
- Check the [documentation](../README.md) for detailed information

Happy analyzing! 🧠🔬

# DMCC Sherlock Bundle

This folder contains the minimum Sherlock-side bundle for expanding the DMCC
pilot beyond the local 4-subject run.

## What It Does

- `sync_patrick_control_to_sherlock.sh`
  - local helper to sync this bundle plus the screened next-batch subject list
- `download_dmcc_subject_s3.sh`
  - Sherlock-side shell downloader for one DMCC subject from OpenNeuro S3
- `dmcc_fmriprep_array.sbatch`
  - Sherlock job-array template for one-subject-per-array-task fMRIPrep

## Suggested Sherlock Layout

- code bundle: `~/brain_researcher_dmcc`
- raw and derivatives: `$SCRATCH/brain_researcher_dmcc`
- durable shared containers or finalized outputs: move to `$PI_HOME` or `$OAK` later

## Local Sync

```bash
bash scripts/analysis/cognitive_control/sherlock/sync_patrick_control_to_sherlock.sh \
  <sunet>@login.sherlock.stanford.edu \
  ~/brain_researcher_dmcc
```

## Sherlock Submission

```bash
cd ~/brain_researcher_dmcc
mkdir -p logs
N=$(wc -l < outputs/patrick_congnitive_control/dmcc_subject_screening/next_batch.txt)
sbatch -p russpold --qos=russpold \
  --array=1-${N}%4 \
  scripts/analysis/cognitive_control/sherlock/dmcc_fmriprep_array.sbatch \
  outputs/patrick_congnitive_control/dmcc_subject_screening/next_batch.txt \
  ~/brain_researcher_dmcc
```

If your Sherlock account uses a different partition or qos, replace
`-p russpold --qos=russpold` with the appropriate values.

# Paper 2 Local Dataset Battery (OpenNeuro)

This runbook uses local `brain_researcher` repo scripts plus the
`dataset-loader-openneuro` skill resolver.

## Battery

- `ds000114` (standard task-fMRI scenario)
- `ds004873` (calibrated/interpretability anchor scenario)
- `ds003999` (LNM scenario)

## Probe Command

```bash
scripts/paper2_probe_openneuro_battery.sh light fmri-glm
```

Or directly:

```bash
~/.codex/skills/dataset-loader/scripts/resolve_openneuro.sh \
  --dataset ds000114 --mode light --analysis-goal fmri-glm
```

## Snapshot (2026-02-19)

- `ds000114`: `status=ok`, `resolved_path=/app/data/openneuro/ds000114`
- `ds004873`: `status=not_found` (metadata-only / not mounted locally)
- `ds003999`: `status=not_found` (metadata-only / not mounted locally)

## Next Steps When Not Found

1. Mount OpenNeuro:

```bash
bash <repo>/scripts/setup/mount_openneuro_s3fs.sh
```

2. Re-run probe:

```bash
scripts/paper2_probe_openneuro_battery.sh light fmri-glm
```

3. If mount remains unavailable, use resolver-provided selective download
   commands (`download_plan.commands`) instead of full bucket sync.

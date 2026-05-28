# Running Brain Researcher on HPC / SLURM Clusters

Brain Researcher ships with generic SLURM helpers that can target any
cluster — not just Stanford Sherlock. The original Sherlock workflow is
preserved as the default profile, but adding your own cluster is just a
YAML file.

## Quick start (any SLURM cluster)

1. Copy the template:

   ```bash
   cp configs/slurm/profiles/generic_slurm.yaml \
      configs/slurm/profiles/<your_cluster>.yaml
   ```

2. Edit `<your_cluster>.yaml` and replace `REPLACE_ME` values:
   - `account` — your SLURM allocation
   - `interactive_partition` / `batch_partition` — partitions you have
     access to (verify via `sinfo -s`)
   - `interactive_qos` / `batch_qos` — QoS if your cluster uses them
     (leave `""` if not)
   - `module_use` — optional pre-staged module path
   - Update `name:` field to match the filename

3. Select your profile:

   ```bash
   export BR_SLURM_PROFILE=<your_cluster>
   ```

   Or pass `profile=<your_cluster>` to MCP tool calls.

## How profile loading works

`src/brain_researcher/services/mcp/slurm_tools.py` discovers profiles at
import time by globbing `configs/slurm/profiles/*.yaml`. Each YAML's
`name:` field (or filename stem) becomes a key in the `CLUSTER_PROFILES`
dict that the MCP tools (`sherlock_guide`, `sherlock_slurm` — Phase B-1b
will rename to `slurm_guide`, `slurm_submit`) read from.

A small inline fallback for `sherlock_default` lives in the module so
that wheel installs without bundled configs/ still work.

## Default profile

The `BR_SLURM_PROFILE` env var sets the global default. Unset, it falls
back to `sherlock_default` (Stanford-specific). On non-Stanford
clusters, always set this env var before running so error messages and
generated sbatch scripts point at the right partitions.

## What the MCP SLURM tools do (and don't)

The helpers are intentionally read-mostly:

- **Render**: produce sbatch scripts from a cluster profile + intent
- **Validate**: parse `#SBATCH` directives and flag missing/invalid ones
- **Patch**: in-place edit a script to add/change a directive
- **Inspect**: query local Slurm state (`squeue`, `sacct`, `scontrol`)
- **Diagnose**: parse log tails for common failure modes

They do NOT submit, cancel, or mutate jobs. You run `sbatch` yourself
after reviewing the generated script.

## Adding a new profile — checklist

- [ ] Copy `generic_slurm.yaml` to `<name>.yaml`
- [ ] Replace every `REPLACE_ME`
- [ ] Verify partitions exist via `sinfo -s`
- [ ] Verify QoS via `sacctmgr show qos`
- [ ] Test with `BR_SLURM_PROFILE=<name>` + a dry-run render
- [ ] Submit a small test job manually before trusting auto-generated scripts

## Sherlock-specific docs

For Stanford Sherlock users, the original workflow guidance lives at
`skills/sherlock-oak-workflow/`. The legacy `DEFAULT_PROFILE =
sherlock_default` lookup means existing Sherlock users see no behavior
change post-rename.

# Root Legacy Scripts

This directory is a holding area for scripts that used to live at the repository
root or under older service paths. It exists to preserve relocation provenance
while the active command surface stays under the CLI and topical `scripts/`
subdirectories.

Use current entrypoints for new work:

- CLI: `br` or `brain-researcher`
- Web UI: `br serve web` and `apps/web-ui/`
- Service helpers: `scripts/services/`
- BR-KG operations: `scripts/br-kg/`
- Deployment helpers: `scripts/deployment/`
- Release demos: `scripts/demos/README.md`

## File Groups

| Files | Status | Notes |
| --- | --- | --- |
| `check_env.py` | Kept compatibility helper | Contract-tested diagnostic for current repo paths. |
| `launch.py`, `launch_agent.py`, `launch_all.sh`, `launch_services_clean.sh`, `run_langgraph.py` | Historical launchers | Not public release entrypoints. Prefer the CLI, service scripts, or deployment scripts. |
| `debug_services.py`, `working_tools_demo.py`, `demo_enhanced_features.py` | Historical debug/demo helpers | Keep only for relocation provenance unless a current doc or test depends on them. |
| `launch_ingestion.py`, `run_ingestion.sh`, `launch_monitoring_service.py` | Historical ops helpers | Review against current `scripts/br-kg/`, `scripts/services/`, and deployment docs before reuse. |
| `clean_pycache.py`, `get_helm.sh`, `mount_oak.sh` | Local utility fragments | Not part of the public supported command surface. |

## Cleanup Rule

New scripts should not be added here. Put new operational scripts under a
topical `scripts/` subdirectory, document their inputs and outputs, and make
them rerunnable. Remove files from this directory only with reference scans and
the relocation/package-root contract tests.

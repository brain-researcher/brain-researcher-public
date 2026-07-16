# Contributing to Brain Researcher

Thanks for your interest in Brain Researcher. This repository is public code,
contracts, documentation, and service scaffolding for AI-assisted neuroimaging.
Private benchmark corpora, Neo4j graph contents, internal run artifacts, and
site-specific launchers are not shipped here.

By participating in this project you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Report an Issue

Choose the path closest to what you were trying to do:

- [Neuroimaging analysis or run problem](https://github.com/brain-researcher/brain-researcher-public/issues/new?template=01-neuroimaging-analysis.yml):
  an fMRI, diffusion, structural, EEG/MEG, surface, or meta-analysis workflow
  failed, blocked, or produced a questionable result.
- [Request a tool or workflow](https://github.com/brain-researcher/brain-researcher-public/issues/new?template=02-tool-workflow-request.yml):
  a tool, recipe, MCP capability, or UI workflow is missing or hard to find.
- [Dataset or metadata issue](https://github.com/brain-researcher/brain-researcher-public/issues/new?template=03-dataset-metadata.yml):
  dataset search, BIDS metadata, access status, or Add-to-Plan behavior looks
  wrong.
- [Scientific validity concern](https://github.com/brain-researcher/brain-researcher-public/issues/new?template=04-scientific-validity.yml):
  a default, workflow order, statistical model, atlas/space choice, evidence
  grounding, or interpretation seems scientifically risky.
- [Docs, setup, or MCP problem](https://github.com/brain-researcher/brain-researcher-public/issues/new?template=05-docs-setup.yml):
  README, environment variables, MCP setup, Web UI, Docker, Python install, or
  service startup is confusing or broken.

If none of those fit, open a blank issue:
<https://github.com/brain-researcher/brain-researcher-public/issues/new>.

For vulnerabilities, do not open a public issue. Use
[`SECURITY.md`](SECURITY.md).

## What to Include

For neuroimaging reports, the most useful details are:

- Modality: fMRI, diffusion MRI, structural MRI, surface, EEG/MEG, or
  meta-analysis.
- Data source: OpenNeuro ID, local BIDS dataset, HCP, UKB, atlas, synthetic
  data, or unknown.
- Entry point: Web UI, MCP client, CLI, Python API, Docker, or docs.
- Workflow or tool: for example fMRIPrep, MRIQC, FreeSurfer, MRtrix, FSL,
  Nilearn, NiMARE, or Brain Researcher MCP planning.
- What you expected and what happened instead.
- Error text, screenshots, logs, or copied output when available.

Do not include PHI, private dataset paths, API keys, tokens, cloud secrets, or
Neo4j passwords.

## Development Setup

```bash
git clone https://github.com/brain-researcher/brain-researcher-public.git
cd brain-researcher-public
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[all]"
cp .env.example .env
```

Add one LLM provider key to `.env` if you need runtime LLM behavior. See
[`docs/ENVIRONMENT_SETUP.md`](docs/ENVIRONMENT_SETUP.md) for provider-specific
setup.

For the full local stack, follow the service walkthrough in
[`README.md`](README.md) and [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
Some surfaces require local API keys, data mounts, Neo4j state, or
deployment-specific services.

## Pull Requests

1. Open or link an issue for non-trivial changes.
2. Create a focused branch:

```bash
git checkout -b <type>/<short-slug>
```

Useful prefixes are `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, and
`perf`.

3. Keep the change scoped. Separate behavior changes, refactors, and docs-only
   updates when practical.
4. Update docs for user-facing changes.
5. Run the narrowest meaningful local validation and include the command output
   in the PR body.

Examples:

```bash
python -m py_compile path/to/changed_file.py
python -m pytest tests/unit -x
bash scripts/dev/docs_manager.sh check
git diff --check
```

GitHub Actions runs the clean-install, unit, contract, reproducibility,
documentation, service, Web, and static-deployment jobs on pull requests.
Network downloads and larger scientific reruns run in the separate scheduled
workflow, so a green pull request does not by itself claim that every governed
or external-data analysis was rerun. Maintainers may also run focused local
checks before merge.

Use the [pull request template](.github/pull_request_template.md) and include:

- What changed and why.
- Linked issue or discussion, if any.
- What you ran locally.
- What remains out of scope.

## Maintainer Release Procedure

A green pull request is necessary but is not the software release gate. For a
version declared in [`release/manifest.json`](release/manifest.json), a
maintainer must complete this sequence from the exact intended release commit:

1. Dispatch `.github/workflows/release-readiness.yml` at that commit with the
   exact `release_version`.
2. Require the workflow to pass, download its Actions artifact, verify
   `release-gate-report.json` says `status: passed`, and confirm
   `source-commit.txt` matches the intended commit.
3. Create the annotated `v<version>` tag at that same commit only after step 2.
4. Publish the GitHub Release and permanently attach
   `release-gate-report.json`, `source-commit.txt`, `versions.json`,
   `SHA256SUMS`, and `release-gate-evidence.tar.gz` from the verified artifact.
5. Recheck the remote tag, Release target, and attached assets. The workflow
   does not publish containers, Helm charts, deployments, or services.

The temporary Actions artifact is retained for only 30 days. The GitHub Release
attachments are therefore the durable source-commit binding required by the
release manifest.

## Repository Conventions

- Do not commit secrets, real `.env` files, PHI, tokens, cloud credentials, or
  Neo4j passwords.
- Do not commit absolute machine-specific paths such as `/home/<user>/...` into
  source, configs, or active docs.
- Use repo-relative paths, environment variables, or documented config roots.
- Large generated benchmark bundles and private run artifacts are not part of
  the public release surface.
- New analysis tools should live under
  `src/brain_researcher/services/tools/`, with matching contracts/config/docs
  where applicable.

## Recognition

Significant contributions may be acknowledged in release notes, project
documentation, or `CITATION.cff`. The project uses the MIT license.

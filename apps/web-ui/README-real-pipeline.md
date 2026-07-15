# Real pipeline execution E2E

This opt-in Playwright suite creates a real analysis through
`POST /api/analyses`, waits for a terminal status, checks for artifacts, downloads
the export bundle, and opens the run-detail page. It creates persistent run
state and can take many minutes.

It is separate from the deterministic PRD test gate. A catalog match alone is
not enough: the selected template must have real input data that the executor
can read.

## Before you start

Run every command in this guide from the **repository root**, the directory that
contains `pyproject.toml`, `apps/`, and `scripts/`.

You need:

- Node and Python dependencies installed
- Agent on `http://localhost:8000`
- Orchestrator on `http://localhost:3001`
- BR-KG on `http://localhost:5000` when dataset resolution uses the catalog
- a root `.env` with `JWT_SECRET_KEY` or `NEXTAUTH_SECRET`; the same signing
  secret must be visible to the Web UI, Agent, and Orchestrator
- a preprocessed BOLD image, or other template-specific input, staged at a path
  visible to the actual executor

If `.env` does not exist yet, copy `.env.example` to `.env` and replace its
placeholder values before starting the services. Do not commit `.env` or the
generated test token.

## One-time setup

```bash
cd "$(git rev-parse --show-toplevel)"

npm --prefix apps/web-ui ci
npm --prefix apps/web-ui run e2e:install

cp apps/web-ui/.env.test.template apps/web-ui/.env.test.local
# Edit apps/web-ui/.env.test.local for your services, dataset, template, and data path.
```

`apps/web-ui/.env.test.local` is ignored by Git. If you prefer to work inside the
Web UI directory, you may `cd apps/web-ui` and omit `--prefix apps/web-ui` from
the npm commands; return to the repository root before generating the token.

## Load the environment and generate a token

Run this block in every terminal used for the test or its local Web server:

```bash
cd "$(git rev-parse --show-toplevel)"

set -a
source .env
source apps/web-ui/.env.test.local
set +a

export BR_TEST_TOKEN="$(
  python3 scripts/maintenance/generate_e2e_auth_token.py
)"
```

Plain `source` does not export assignments to child processes, so keep the
`set -a` / `set +a` lines. The token generator prints the token into the
environment variable; do not paste it into a tracked file.

## Choose one Web UI mode

### Option A: let Playwright manage port 3002

This is the simplest path. Agent, Orchestrator, and BR-KG must already be
running, but Playwright starts and stops the Web UI itself.

```bash
unset BR_WEB_URL E2E_BASE_URL BASE_URL
npm --prefix apps/web-ui run e2e:real
```

With all three URL variables unset, the harness starts `npm run dev:3002` and
uses `http://localhost:3002`.

### Option B: use an existing local Web UI on port 3000

Load the environment block above in both terminals.

Terminal A:

```bash
npm --prefix apps/web-ui run dev
```

Terminal B:

```bash
export BR_WEB_URL=http://localhost:3000
npm --prefix apps/web-ui run e2e:real
```

Setting `BR_WEB_URL` disables Playwright's managed Web server. This documented
external-server path is for the local Next.js dev server; it is not a claim that
the production Docker authentication path has been validated by this suite.

## Dataset ID versus executable data

`BR_TEST_DATASET_ID` selects catalog metadata and is used by the catalog search
and detail checks. It does **not** download, preprocess, or mount an image.

For the default connectivity template, set `BR_TEST_PARAMS_JSON` to valid JSON
whose paths are visible inside the execution environment. For example, a
containerized executor might use:

```bash
BR_TEST_PARAMS_JSON='{"img":"/app/data/path/to/preprocessed_bold.nii.gz","output_dir":"/app/data/agent_outputs/e2e-real"}'
```

The whole JSON value must be quoted. Replace the example paths with real staged
inputs; do not assume the default `ds:openneuro:ds000001` catalog record provides
those files.

## What success proves

A passing run proves that this configured stack completed these specific checks:

1. the Agent health proxy responded;
2. catalog search and dataset detail resolved;
3. `POST /api/analyses` created a run;
4. the run reached `completed` and exposed at least one artifact;
5. its export endpoint returned a non-empty body; and
6. the local run-detail page rendered the completed state.

It does not prove that every dataset/template combination is executable or that
the normal PRD gate runs real analyses.

## Common failures

- `Real pipeline E2E requires a bearer token`: reload the environment block and
  confirm the signing secret is set before generating `BR_TEST_TOKEN`.
- `No datasets returned`: start BR-KG/catalog or choose a dataset ID present in
  that runtime.
- analysis failure mentioning a missing file: stage the input and correct
  `BR_TEST_PARAMS_JSON` for the executor's filesystem, not only the host shell.
- HTTP 402 from analysis creation: keep `BR_CREDITS_ENFORCEMENT=0` for this local
  test or provision credits explicitly.
- unexpected port 3000 behavior while using Option A: unset `BR_WEB_URL`,
  `E2E_BASE_URL`, and `BASE_URL` before launching the test.

Failure artifacts are written under `artifacts/playwright-real/` and the HTML
report under `artifacts/playwright-report-real/`.

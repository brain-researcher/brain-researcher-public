# Redaction policy

Single source of truth for what gets scrubbed before crossing the public-facing boundary. The rules are implemented by `brain_researcher.services.shared.log_scrubber` and re-exported as `br.redaction.scrub_text` / `br.redaction.scrub_data`.

## What gets scrubbed today

`scrub_text` / `scrub_data` currently target credential-shaped strings only:

- API key prefixes (`sk-`, `sk-ant-`, `sk-or-`, etc.)
- Bearer-token-looking strings
- JWT-shaped strings (three base64 segments separated by `.`)
- AWS-style access keys
- Long hex strings that match common secret patterns

The scrubber **does not** currently rewrite:

- Absolute filesystem paths (`/home/<user>/...`, `/data/...`, `/oak/...`)
- Email addresses
- Internal hostnames or LAN IPs
- Subject IDs / participant IDs
- Internal project codenames

## What this means for OSS publishing

For the v0.1.0 carve, the contract is:

| Surface | Path leakage risk | Policy |
|---|---|---|
| `server_info` response fields `run_root` / `run_roots_read` / `allowed_roots` | Exposes host filesystem layout | Set `disclose_paths=false` (default in OSS deployments) and the path fields return `<redacted>`. |
| `pipeline_plan_validate` / `pipeline_plan_review` echo back caller paths | Mirrors caller input, no server-side leakage | Document as "echoes paths from input; server does not add its own." |
| `scientific_report_generate.local_workspace` | Caller-supplied path, only used as a handoff pointer | Documented in the docstring; server never opens it. |
| `run_scorecard.run_dir` in response | Host path | Apply same `disclose_paths` gate. |
| Log output | API keys / tokens / bearer strings | `scrub_text` / `scrub_data` strip these. |
| Log output | Absolute /home or /data paths | **Not stripped today.** Either run the server in an environment where the host root is non-sensitive, or wrap log handlers with a custom regex filter. |

## Replace-before-publishing rules (when sanitizing source for OSS carve)

When carving `brain_researcher` into `brain-researcher-public`, the following find/replace runs in addition to `scrub_text`:

| Pattern | Replace with |
|---|---|
| `/home/zijiaochen/`, `/home/<other>/` | `${HOME}/` or `${WORKSPACE}/` |
| `your.name@example.com`, other personal emails | `person@example.com` |
| Internal hostnames | `host.local` |
| Subject IDs from private datasets | `subject_001`, `subject_002`, ... |
| Internal project codenames | `public-demo-project` |
| Lab-specific shared roots (e.g. `/oak/stanford/groups/<lab>/`) | `${PI_GROUP_DATA}/` |
| API keys / OAuth client secrets | `${REDACTED}` placeholder |

These rules are enforced once during the W10 Phase 2 carve. They are not currently enforced at runtime — runtime relies on env-var indirection (no secrets in source files).

## Preserve list

Do not strip:

- Schema names, error class names, status codes
- Relative workflow order and step ids
- File shapes / sizes / sha256
- Tool names and parameter names

## Known gaps to close in v0.2

- Extend `scrub_text` to optionally redact `/home/<user>/` and lab-shared roots when run in `public_mode`. Until then, the runtime escape hatch is the `disclose_paths` gate on `server_info`.
- Add a CI step that runs gitleaks + a path-pattern grep on every PR. The pre-commit gitleaks already runs; the path grep is documented in `CONTRIBUTING.md` but not yet auto-enforced.

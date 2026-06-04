# Security Policy

## Supported versions

Brain Researcher is in pre-1.0 OSS preview. Security fixes are applied
to the `main` branch only. Once v1.0 is tagged, this section will be
updated with a published support window.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| pre-1.0 tagged releases | ⚠️ best-effort |

## Reporting a vulnerability

**Please do not file a public GitHub issue** for security
vulnerabilities. Instead, use the private channel below:

**GitHub's private advisory flow**:
[Open a private security advisory](https://github.com/brain-researcher/brain-researcher-public/security/advisories/new).

Please include, where possible:

- A clear description of the issue and the affected component (web UI /
  agent / MCP server / BR-KG / orchestrator / infrastructure)
- Steps to reproduce, or a proof-of-concept
- The commit SHA or release tag you observed the issue on
- Your assessment of impact (data exposure, RCE, auth bypass, etc.)
- Any suggested remediation

## What to expect

- We aim to acknowledge new reports within **3 business days**.
- We will work with you on a fix and coordinated disclosure timeline.
  The default timeline is 90 days from the date of the initial report,
  shorter for high-severity issues.
- Reporters who follow this policy will be credited in the
  `CHANGELOG.md` entry for the fix (unless they prefer to remain
  anonymous).

## Scope

In scope:

- Code in `src/`, `apps/`, `infrastructure/`, `scripts/`,
  `configs/`, and `skills/`
- The default Docker / docker-compose deployment
- The default Kubernetes / Helm chart
- The MCP tool surface and tool-allowlist gating

Out of scope (please do not report):

- Issues that only affect non-default configurations a user
  intentionally enabled (e.g., disabling auth, allowing arbitrary code
  execution via deliberately overpermissive tool allowlists)
- Findings in third-party dependencies that are already disclosed
  upstream (file with the upstream project instead)
- Theoretical issues without a working proof-of-concept
- Generated research artifacts intentionally checked in under `docs/use_cases/`
  (these are frozen records; their content is the research artifact, not the
  running system)

## Hall of Fame

Reporters whose findings have led to a security fix will be listed here
after their fix is published.

_(empty — be the first!)_

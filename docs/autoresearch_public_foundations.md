# Public autoresearch foundations v1

`br.autoresearch.public-foundations.v1` is an experimental, data-contract-only
surface. Its machine-readable manifest is
[`contracts/autoresearch_public_foundations_v1.yaml`](contracts/autoresearch_public_foundations_v1.yaml).

It has `implementation_status: contract_only` and `authority: none`. It is not
an MCP tool contract and does not change the repository's MCP contract epoch.

## Implemented foundations

`brain_researcher.autoresearch.canonical_program_registry` provides the exact
four-part canonical identity used by the production registration boundary:
`program_id`, `program_version`, `executor_id`, and `executor_version`.
`CanonicalProgramDescriptor` retains the production descriptor schema version
`br.canonical_program_descriptor.v1`.

`CanonicalProgramRegistry` starts empty. An application composition root must
explicitly inject a canonical hook with its descriptor, authorization resolver,
and launch-plan builder. The registry never imports, discovers, or invokes
concrete program modules, so generic consumers do not gain a dependency on a
private program implementation.

This foundation does not define authorization terms or issue authority. The
authorization resolver remains an opaque registration hook for later runtime
composition; this registry does not call it.

`brain_researcher.autoresearch.episode_paths` provides the canonical,
future-only episode address and pure path derivation. It does not create files
or directories. For a canonical address, the hierarchy is:

```text
$BR_AUTORESEARCH_DATA_ROOT/research/<line_id>/owners/<owner_key>/
campaigns/<campaign_id>/rounds/<round_id>/episodes/<episode_id>/runs/<run_id>
```

The derived episode tree includes `registration/`, `authority/`, `control/`,
and `runs/`. A run derives `execution/`, `outputs/`, `society/`, `public/`, and
`private/` subtrees. Retrying an unchanged episode changes only `run_id`.

With no explicit `data_root` and no non-empty `BR_AUTORESEARCH_DATA_ROOT`, the
canonical fallback is `/data/brain_researcher`. An explicit root takes highest
precedence, followed by the environment override.

## Deferred to PR B

The public surface does not yet expose an outer-loop state machine, Goal
handoff, CandidateBundle, Society review, or run watch contract. It also does
not implement storage, authorization, dispatch, recovery, execution, or a
Society runner. Those require a separately reviewed runtime integration and
must not be inferred from these foundations.

The runtime should be released in capability-complete slices rather than by
copying the private deployment: B1 may add the owner-scoped Goal-to-reward
control plane, B2 may add an injected confirmation/launch adapter, and B3 may
add a generic run-event/watch contract. Until those slices exist, an Agent Kit
workflow that requires contract `2026-07-31` is a hosted-or-compatible-server
client, not a self-hosted capability supplied by this foundation.

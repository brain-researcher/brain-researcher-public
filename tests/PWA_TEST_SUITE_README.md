# PWA test fixtures (legacy)

## Current status

These are legacy, mock-heavy fixtures. They are **not** a current PWA release
gate and do not verify the production service worker, push backend, offline
workflow, or mobile UI end to end.

The old version of this README described integration and end-to-end tests,
package scripts, and a Docker test stack that are not present in the public
repository. Do not use it as evidence that those workflows have been tested.

## What is actually here

| Fixture | What it exercises | Current runner status |
|---|---|---|
| `tests/unit/pwa/test_push_notifications.py` | Standalone mock classes for subscription, delivery, scheduling, and metrics behavior | Runnable with pytest; does not import the Web UI push implementation |
| `tests/unit/pwa/test_service_worker.js` | Inline mock service-worker handlers and browser APIs | Not wired to the current Vitest configuration; does not load either production service worker |
| `tests/unit/components/test_mobile_components.tsx` | Inline mock React components and PWA state | Not wired to the current Vitest configuration; does not import the production mobile components |

The production surfaces are separate:

- [`apps/web-ui/public/service-worker.js`](../apps/web-ui/public/service-worker.js)
  and [`apps/web-ui/public/sw.js`](../apps/web-ui/public/sw.js)
- [`apps/web-ui/src/lib/push-notifications.ts`](../apps/web-ui/src/lib/push-notifications.ts)
- [`apps/web-ui/src/components/mobile/`](../apps/web-ui/src/components/mobile/)

## Runnable check

From the repository root, after installing the Python test dependencies as
described in the [test-suite guide](README_TESTING.md):

```bash
python -m pytest -q -p no:cacheprovider \
  --confcutdir=tests/unit/pwa \
  tests/unit/pwa/test_push_notifications.py
```

This checks the standalone Python mock behavior only. It does not start the Web
UI, register a browser service worker, contact a push service, or exercise an
offline browser workflow.

There is currently no supported `npm run test:pwa`, `npm run start:test`, PWA
Playwright spec, or `docker-compose.test.yml` in this repository.

## What a real PWA gate still needs

Restoring PWA coverage is implementation work, not a documentation-only step.
A useful follow-up should:

1. Add Vitest specs under `apps/web-ui/tests/` that import the real push and
   mobile implementations.
2. Test the production service-worker build or registration path instead of
   reimplementing handlers inside a fixture.
3. Add a Playwright workflow that verifies install, offline, update, and
   reconnection behavior against a running Web UI.
4. Wire the resulting commands into `apps/web-ui/package.json` and CI, then
   document only the commands that pass there.

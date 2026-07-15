# Cloudflare hosting note

> **Status: experimental and not verified.** The public tree contains an
> experimental adapter dependency and local `build:cloudflare` script, but it
> does not ship a Wrangler deployment configuration, verified hosted
> environment, domain, release workflow, or runtime smoke. Do not treat this
> file as a production deployment guide.

The Web UI uses Next.js server routes and proxies requests to Brain Researcher
backend services. A Cloudflare deployment therefore needs an operator-owned
design for the supported Next.js runtime, backend reachability, authentication,
secrets, WebSockets, CORS, observability, and rollback. Those decisions are
outside the public repository's deployment contract.

## Local build check

For the local check, use Node 20 and npm 10. Run from the repository root:

```bash
npm --prefix apps/web-ui ci
npm --prefix apps/web-ui run build
```

For a future hosting experiment, the project setting would start with
`Root directory: apps/web-ui`, but a successful local build does not prove that
the app runs correctly on Cloudflare. Verify both backend API responses and the
rendered browser state before documenting any hosted target as supported.

The old unverified click-through walkthrough is retained only as an
[exact Git snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/apps/web-ui/CLOUDFLARE_DEPLOYMENT.md).

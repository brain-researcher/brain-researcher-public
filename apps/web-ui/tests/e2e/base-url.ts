// The default Playwright server is isolated from the normal Web UI dev port.
export function resolveE2EBaseUrl() {
  return process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3002'
}

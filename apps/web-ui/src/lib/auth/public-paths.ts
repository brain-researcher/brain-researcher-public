const PUBLIC_EXACT_PATHS = new Set([
  '/',
  '/explore',
  '/demo',
  '/demos',
  '/run',
  '/share',
  '/benchmarks',
  '/charts',
  '/library',
  '/tools',
  '/understand-br',
  '/docs',
  '/datasets',
  '/vault/datasets',
  '/terms',
  '/privacy',
  '/robots.txt',
  '/sitemap.xml',
  '/login',
  '/auth/login',
  '/auth/signup',
  '/auth/forgot',
  '/auth/callback',
  '/auth/verify-request',
  '/auth/error',
  '/studio/plan-preview',
  '/api/auth',
  '/api/orchestrator/auth/signup',
  '/api/orchestrator/auth/reset-password',
  '/api/health',
  '/api/agent/health',
  '/health',
  '/api/chat',
  '/api/catalog',
  '/api/analyses',
  '/api/datasets',
  '/api/demo',
  '/api/files',
  '/api/viz/demo',
  '/api/share',
  '/api/kg',
  '/api/br-kg',
  '/api/search',
  '/kg',
  '/br-kg',
  '/mcp/setup',
  '/api/workflows',
  '/api/tools',
])

const PUBLIC_PREFIX_PATHS = [
  '/api/auth',
  '/api/orchestrator/auth/signup',
  '/api/health',
  '/api/agent/health',
  '/api/chat',
  '/api/catalog',
  '/api/analyses',
  '/api/datasets',
  '/api/demo',
  '/api/files',
  '/api/viz/demo',
  '/api/share',
  '/api/kg',
  '/api/br-kg',
  '/api/search',
  '/kg',
  '/br-kg',
  '/mcp/setup',
  '/api/workflows',
  '/api/tools',
  '/explore',
  '/demo',
  '/demos',
  '/run',
  '/share',
  '/benchmarks',
  '/charts',
  '/library',
  '/tools',
  '/docs',
  '/datasets',
]

function isLocalStudioBypassEnabled(): boolean {
  if (process.env.NEXT_PUBLIC_STUDIO_PUBLIC_DEV === 'true') {
    return true
  }

  return process.env.NODE_ENV === 'development'
}

export function isPublicPath(pathname: string): boolean {
  if (
    isLocalStudioBypassEnabled() &&
    (pathname === '/studio' || pathname.startsWith('/studio/'))
  ) {
    return true
  }

  if (PUBLIC_EXACT_PATHS.has(pathname)) {
    return true
  }

  return PUBLIC_PREFIX_PATHS.some((prefix) => pathname.startsWith(`${prefix}/`))
}

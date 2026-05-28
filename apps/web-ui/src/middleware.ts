import { withAuth, type NextRequestWithAuth } from 'next-auth/middleware'
import { NextResponse, type NextRequest } from 'next/server'
import type { JWT } from 'next-auth/jwt'
import { jwtVerify } from 'jose'

import {
  readBestBearerTokenFromCookies,
  readNextAuthSessionToken,
} from '@/lib/auth/cookie-tokens'
import { isPublicPath } from '@/lib/auth/public-paths'

const WORKSPACE_COOKIE = 'br_workspace_id'
const WORKSPACE_HEADER = 'x-workspace-id'
const E2E_AUTH_COOKIE = 'br_e2e_auth'

function renderAnalysesGone(isAuthenticated: boolean): NextResponse {
  const ctaHref = isAuthenticated ? '/hub' : '/auth/login?callbackUrl=%2Fhub'
  const ctaLabel = isAuthenticated ? 'Open Studio' : 'Sign in'
  const authLine = isAuthenticated
    ? ''
    : '<p style="margin-top:0.75rem;color:#475569;font-size:0.875rem;">Sign in to see your runs in Studio.</p>'
  const body = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Runs has moved into Studio · Brain Researcher</title>
<meta name="robots" content="noindex">
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f9fafb;color:#0f172a;margin:0;padding:4rem 1rem;}
.card{max-width:36rem;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:1rem;padding:2.5rem;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.04);}
h1{font-size:1.5rem;font-weight:600;margin:0 0 0.75rem;}
p{margin:0;color:#475569;font-size:0.875rem;line-height:1.5;}
a.btn{display:inline-block;margin-top:1.5rem;padding:0.5rem 1rem;background:#0f172a;color:#fff;text-decoration:none;border-radius:0.5rem;font-size:0.875rem;font-weight:500;}
a.btn.secondary{background:#fff;color:#0f172a;border:1px solid #cbd5e1;margin-left:0.5rem;}
</style>
</head>
<body>
<main class="card">
<h1>Runs has moved into Studio</h1>
<p>Open Studio to see your activity in the right sidebar. Each Studio session now ships with a Runs drawer that auto-refreshes and lets you attach a run into the open notebook with one click.</p>
${authLine}
<a class="btn" href="${ctaHref}">${ctaLabel}</a>
<a class="btn secondary" href="/">Back to home</a>
</main>
</body>
</html>`
  return new NextResponse(body, {
    status: 410,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
    },
  })
}

function maybeRedirectLegacyLocalePrefix(req: NextRequest): NextResponse | null {
  const { pathname } = req.nextUrl
  if (pathname === '/en' || pathname.startsWith('/en/')) {
    const url = req.nextUrl.clone()
    url.pathname = pathname === '/en' ? '/' : pathname.replace(/^\/en\//, '/')
    return NextResponse.redirect(url)
  }
  return null
}

function nextWithWorkspaceHeaders(req: NextRequest): NextResponse {
  const requestHeaders = new Headers(req.headers)

  const workspaceId = req.cookies.get(WORKSPACE_COOKIE)?.value?.trim()
  if (workspaceId && !requestHeaders.get(WORKSPACE_HEADER)) {
    requestHeaders.set(WORKSPACE_HEADER, workspaceId)
  }

  const { pathname } = req.nextUrl
  if (pathname.startsWith('/api') && !pathname.startsWith('/api/auth')) {
    const accessToken =
      readNextAuthSessionToken(req.cookies) || readBestBearerTokenFromCookies(req.cookies)

    if (!requestHeaders.get('authorization')) {
      if (accessToken) {
        requestHeaders.set('authorization', `Bearer ${accessToken}`)
      }
    }
  }

  return NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  })
}

const baseMiddleware = (req: NextRequest) => {
  const { pathname } = req.nextUrl
  const authToken = (req as any)?.nextauth?.token as JWT | undefined
  const e2eCookieAuth =
    process.env.NODE_ENV !== 'production' && req.cookies.get(E2E_AUTH_COOKIE)?.value === '1'

  // Normalize legacy chat route to the hosted Marimo hub.
  if (pathname === '/chat') {
    const url = req.nextUrl.clone()
    url.pathname = '/hub'
    return NextResponse.redirect(url)
  }

  // Canonicalize legacy Explore landing to `/` (preserve query params).
  if (pathname === '/explore') {
    const url = req.nextUrl.clone()
    url.pathname = '/'
    return NextResponse.redirect(url)
  }

  // Canonicalize Knowledge Graph routes to /kg (preserve query params).
  if (pathname === '/knowledge-graph' || pathname.startsWith('/knowledge-graph/')) {
    const url = req.nextUrl.clone()
    url.pathname = pathname.replace(/^\/knowledge-graph/, '/kg')
    return NextResponse.redirect(url)
  }

  if (pathname === '/neurokg' || pathname.startsWith('/neurokg/')) {
    const url = req.nextUrl.clone()
    url.pathname = pathname.replace(/^\/neurokg/, '/kg')
    return NextResponse.redirect(url)
  }

  // /analyses retired in favour of the Studio Runs sidebar at /hub. Emit a real
  // HTTP 410 (Gone) with an auth-branched HTML body. Detail routes like
  // /analyses/[analysisId] still render normally — only the exact /analyses index
  // is gone.
  if (pathname === '/analyses') {
    return renderAnalysesGone(Boolean(authToken))
  }

  // Canonicalize legacy routes to the new IA (preserve query params).
  // Keep the legacy pages for deep links, but prefer Analysis-first destinations.
  if (pathname === '/runs' || pathname.startsWith('/runs/')) {
    const url = req.nextUrl.clone()
    url.pathname = pathname.replace(/^\/runs/, '/analyses')
    return NextResponse.redirect(url)
  }

  if (pathname === '/files') {
    const url = req.nextUrl.clone()
    url.pathname = '/vault/files'
    return NextResponse.redirect(url)
  }

  // Allow public paths
  if (isPublicPath(pathname)) {
    return nextWithWorkspaceHeaders(req)
  }

  return nextWithWorkspaceHeaders(req)
}

// Use same secret as NextAuth API (needed so middleware decode recognizes session on all protected routes)
const authSecret =
  typeof process.env.JWT_SECRET_KEY === 'string' && process.env.JWT_SECRET_KEY
    ? process.env.JWT_SECRET_KEY
    : typeof process.env.NEXTAUTH_SECRET === 'string' && process.env.NEXTAUTH_SECRET
      ? process.env.NEXTAUTH_SECRET
      : undefined

const nextAuthMiddleware = withAuth(baseMiddleware, {
  secret: authSecret,
  jwt: {
    decode: async ({ token, secret }) => {
      if (!token) return null
      const secretStr =
        (typeof secret === 'string' ? secret : secret?.toString() || '') ||
        process.env.JWT_SECRET_KEY ||
        process.env.NEXTAUTH_SECRET ||
        ''
      if (!secretStr) return null
      try {
        const { payload } = await jwtVerify(token, new TextEncoder().encode(secretStr), {
          algorithms: ['HS256'],
        })
        return payload as JWT
      } catch {
        return null
      }
    },
  },
  callbacks: {
    authorized: ({ token, req }) => {
      const { pathname } = req.nextUrl
      const e2eCookieAuth =
        process.env.NODE_ENV !== 'production' && req.cookies.get(E2E_AUTH_COOKIE)?.value === '1'

      // Allow public paths
      if (isPublicPath(pathname)) {
        return true
      }

      // For protected routes, require valid token
      return Boolean(token) || e2eCookieAuth
    },
  },
  pages: {
    signIn: '/auth/login',
  },
})

const supabaseEnabled = Boolean(
  process.env.SUPABASE_URL ||
    process.env.NEXT_PUBLIC_SUPABASE_URL ||
    process.env.SUPABASE_ANON_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    process.env.SUPABASE_PUBLISHABLE_DEFAULT_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY
)

type AuthProvider = 'supabase' | 'nextauth' | 'both'

const resolveAuthProvider = (): AuthProvider => {
  const raw = (process.env.BR_AUTH_PROVIDER || process.env.NEXT_PUBLIC_AUTH_MODE || '')
    .trim()
    .toLowerCase()

  if (raw === 'supabase') return supabaseEnabled ? 'supabase' : 'nextauth'
  if (raw === 'nextauth') return 'nextauth'
  if (raw === 'both') return supabaseEnabled ? 'both' : 'nextauth'

  return supabaseEnabled ? 'supabase' : 'nextauth'
}

const authProvider = resolveAuthProvider()

export default function middleware(req: NextRequest | NextRequestWithAuth, ev?: unknown) {
  const legacyLocaleRedirect = maybeRedirectLegacyLocalePrefix(req as NextRequest)
  if (legacyLocaleRedirect) return legacyLocaleRedirect

  if (authProvider !== 'nextauth') {
    // Supabase (and "both") store sessions in browser storage; skip NextAuth enforcement.
    return baseMiddleware(req)
  }

  return nextAuthMiddleware(req as NextRequestWithAuth, ev as any)
}

export const config = {
  matcher: [
    {
      /*
       * Match all request paths except:
       * - _next/static (static files)
       * - _next/image (image optimization files)
       * - favicon.ico (favicon file)
       * - common image assets
       *
       * Also skip websocket upgrade requests entirely. Next.js runs middleware
       * request handling on an upgrade socket without a normal response object,
       * which trips local `next dev` on proxied `/ws/*` traffic.
       */
      source: '/((?!_next/static|_next/image|favicon.ico|.*\\.png$|.*\\.jpg$|.*\\.svg$).*)',
      missing: [
        {
          type: 'header',
          key: 'upgrade',
          value: 'websocket',
        },
      ],
    },
  ],
}

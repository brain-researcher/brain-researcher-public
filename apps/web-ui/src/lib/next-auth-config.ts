import type { NextAuthOptions } from 'next-auth'
import GoogleProvider from 'next-auth/providers/google'
import GitHubProvider from 'next-auth/providers/github'
import AzureADProvider from 'next-auth/providers/azure-ad'
import CredentialsProvider from 'next-auth/providers/credentials'
import { SignJWT, jwtVerify } from 'jose'
import { encode as encodeJwt } from 'next-auth/jwt'

import { resolveOrchestratorBaseUrl as resolveSharedOrchestratorBaseUrl } from '@/lib/server/downstream'
import { resolveSharedJwtSecret } from '@/lib/server/shared-jwt-secret'

const signJwtHS256 = async (token: Record<string, unknown>, secret: string, maxAge?: number) => {
  const expSeconds = Math.floor(Date.now() / 1000) + (maxAge ?? 30 * 24 * 60 * 60)
  return await new SignJWT(token)
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setExpirationTime(expSeconds)
    .setIssuedAt()
    .sign(new TextEncoder().encode(secret))
}

// Optional: dev-only credentials auth gate to avoid accidental prod exposure
const enableDevCredentials = process.env.ENABLE_DEV_CREDENTIALS === '1'
const devCredentialsEmail = process.env.DEV_CREDENTIALS_EMAIL
const devCredentialsPassword = process.env.DEV_CREDENTIALS_PASSWORD
const sharedSecret = resolveSharedJwtSecret()
const nextAuthDebugEnabled =
  process.env.NEXTAUTH_DEBUG === '1' ||
  process.env.NEXTAUTH_DEBUG === 'true' ||
  process.env.BR_AUTH_DEBUG === '1' ||
  process.env.BR_AUTH_DEBUG === 'true'

export const resolveOrchestratorBaseUrl = resolveSharedOrchestratorBaseUrl

const deriveUsername = (email: string) => {
  const stem = email.split('@')[0] || email
  return stem.replace(/[^a-zA-Z0-9_]/g, '_') || 'user'
}

/**
 * Ensure the OAuth user exists in the Orchestrator's unified UserStore.
 * Called from the signIn callback on every OAuth login (idempotent).
 */
const ensureOrchestratorUser = async (
  email: string,
  name?: string | null,
  provider?: string,
  providerAccountId?: string,
  image?: string | null,
): Promise<{ user_id?: string; role?: string }> => {
  const baseUrl = resolveOrchestratorBaseUrl()
  try {
    const res = await fetch(`${baseUrl}/auth/ensure-user`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        name: name || undefined,
        provider: provider || 'unknown',
        providerAccountId: providerAccountId || '',
        image: image || undefined,
      }),
    })
    if (res.ok) {
      const data = await res.json()
      return { user_id: data.user_id, role: data.role }
    }
    console.error('[auth] ensure-user returned', res.status)
  } catch (e) {
    console.error('[auth] Failed to call ensure-user:', e)
  }
  return {}
}

type OrchestratorLoginResult =
  | { ok: true; user: Record<string, any>; access_token?: string }
  | { ok: false; status?: number; detail?: string; error?: string }

const attemptOrchestratorLogin = async (
  username: string,
  password: string
): Promise<OrchestratorLoginResult> => {
  const baseUrl = resolveOrchestratorBaseUrl()
  try {
    const response = await fetch(`${baseUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password,
        remember_me: true,
      }),
    })

    if (!response.ok) {
      const text = await response.text().catch(() => '')
      const detail = text.slice(0, 300)
      return { ok: false, status: response.status, detail }
    }

    const data = await response.json().catch(() => ({}))
    return {
      ok: true,
      user: data?.user || data?.user_info || data,
      access_token: typeof data?.access_token === 'string' ? data.access_token : undefined,
    }
  } catch (error) {
    console.error('[auth] orchestrator login request failed', {
      username,
      baseUrl,
      error: error instanceof Error ? error.message : String(error),
    })
    return {
      ok: false,
      error: error instanceof Error ? error.message : 'orchestrator_unreachable',
    }
  }
}

export const authOptions: NextAuthOptions = {
  jwt: {
    // Override to emit HS256-signed JWS (compatible with Agent validator)
    encode: async ({ token, secret, maxAge }) => {
      if (!token) return ''
      const secretStr = typeof secret === 'string' ? secret : secret?.toString() || ''
      return await signJwtHS256(token as any, secretStr, maxAge)
    },
    decode: async ({ token, secret }) => {
      if (!token) return null
      const secretStr = typeof secret === 'string' ? secret : secret?.toString() || ''
      const { payload } = await jwtVerify(token, new TextEncoder().encode(secretStr), { algorithms: ['HS256'] })
      return payload as any
    },
  },
  secret: sharedSecret,
  session: {
    strategy: 'jwt',
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },

  providers: [
    CredentialsProvider({
      name: 'credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          throw new Error('Email and password are required')
        }

        if (
          enableDevCredentials &&
          devCredentialsEmail &&
          devCredentialsPassword &&
          credentials.email === devCredentialsEmail &&
          credentials.password === devCredentialsPassword
        ) {
          return {
            id: devCredentialsEmail,
            email: devCredentialsEmail,
            name: devCredentialsEmail.split('@')[0] || 'dev-user',
            role: 'dev',
          }
        }

        const email = credentials.email.trim()
        const password = credentials.password
        const usernameFromEmail = deriveUsername(email)

        // Try email as username first, then derived username fallback.
        let result = await attemptOrchestratorLogin(email, password)
        if (!result.ok && usernameFromEmail !== email) {
          result = await attemptOrchestratorLogin(usernameFromEmail, password)
        }

        if (!result.ok) {
          const status = 'status' in result ? result.status : undefined
          const detail = 'detail' in result ? result.detail : undefined
          const error = 'error' in result ? result.error : undefined
          console.warn('[auth] credentials login failed', {
            email,
            usernameTried: usernameFromEmail !== email ? [email, usernameFromEmail] : [email],
            status,
            detail,
            error,
            baseUrl: resolveOrchestratorBaseUrl(),
          })
          return null
        }

        const userInfo = result.user || {}
        return {
          id: userInfo.id || usernameFromEmail,
          email: userInfo.email || email,
          name:
            userInfo.full_name ||
            userInfo.fullName ||
            userInfo.username ||
            email.split('@')[0] ||
            usernameFromEmail,
          role: userInfo.role || 'researcher',
          provider: 'orchestrator',
          tenant_id: userInfo.tenant_id || userInfo.tenantId,
          orchestrator_access_token: result.access_token,
        }
      },
    }),

    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? [
          GoogleProvider({
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
            authorization: {
              params: {
                prompt: 'consent',
                access_type: 'offline',
                response_type: 'code',
              },
            },
          }),
        ]
      : []),

    ...((process.env.GITHUB_CLIENT_ID || process.env.GITHUB_ID) && (process.env.GITHUB_CLIENT_SECRET || process.env.GITHUB_SECRET)
      ? [
          GitHubProvider({
            clientId: process.env.GITHUB_CLIENT_ID || process.env.GITHUB_ID!,
            clientSecret: process.env.GITHUB_CLIENT_SECRET || process.env.GITHUB_SECRET!,
          }),
        ]
      : []),

    ...(process.env.AZURE_AD_CLIENT_ID && process.env.AZURE_AD_CLIENT_SECRET
      ? [
          AzureADProvider({
            clientId: process.env.AZURE_AD_CLIENT_ID,
            clientSecret: process.env.AZURE_AD_CLIENT_SECRET,
            tenantId: process.env.AZURE_AD_TENANT_ID || 'common',
          }),
        ]
      : []),
  ],

  pages: {
    signIn: '/auth/login',
    error: '/auth/login',
    verifyRequest: '/auth/verify-request',
  },

  callbacks: {
    // Respect the callbackUrl when it's a same-origin path; otherwise default to /studio.
    async redirect({ url, baseUrl }) {
      // Relative path — prefix with baseUrl
      if (url.startsWith('/')) return `${baseUrl}${url}`
      // Absolute URL on the same origin
      if (url.startsWith(baseUrl)) return url
      // Default post-login destination
      return `${baseUrl}/studio`
    },

    async signIn({ user, account }) {
      // For OAuth providers: ensure the user exists in the Orchestrator's UserStore.
      // This is idempotent – safe to call on every login.
      if (account?.provider && account.provider !== 'credentials') {
        try {
          const result = await ensureOrchestratorUser(
            user.email || '',
            user.name,
            account.provider,
            account.providerAccountId,
            user.image,
          )
          if (result.user_id) {
            // Stash orchestrator user_id so the jwt callback can use it as `sub`
            ;(user as any).orchestratorId = result.user_id
            ;(user as any).role = result.role || 'researcher'
          }
        } catch (e) {
          console.error('[auth] signIn ensure-user error:', e)
          // Don't block sign-in; user just won't have orchestrator API access
        }
      }
      return true
    },

    async jwt({ token, user, account }) {
      // On first sign-in, merge user info into the JWT claims
      if (user) {
        // CRITICAL: use the orchestrator's user_id as `sub` so that
        // get_current_active_user() can resolve the user from UserStore.
        token.sub = (user as any).orchestratorId || (user as any).id || token.sub
        token.email = user.email || token.email
        token.name = user.name || token.name
        token.role = (user as any).role || token.role
        token.provider = account?.provider || token.provider
        // Multi-tenancy foundation: default to 'default' tenant
        token.tenant_id = (user as any).tenant_id || 'default'
        if ((user as any).orchestrator_access_token) {
          ;(token as any).orchestrator_access_token = (user as any).orchestrator_access_token
        }
      }
      return token
    },

    async session({ session, token }) {
      // Attach user info to session object
      if (session.user) {
        session.user.id = token.sub as string | undefined
        session.user.email = token.email as string | undefined
        session.user.name = token.name as string | null | undefined
        session.user.role = token.role as string | undefined
        session.user.provider = token.provider as string | undefined
        session.user.tenant_id = token.tenant_id as string | undefined
      }

      const orchestratorAccessToken = (token as any).orchestrator_access_token
      if (typeof orchestratorAccessToken === 'string' && orchestratorAccessToken) {
        session.accessToken = orchestratorAccessToken
      } else {
        // Expose a signed JWT string for Agent / Authorization header use
        // Use HS256-signed JWS (not JWE) for Agent compatibility
        const sessionSecret =
          sharedSecret ?? (process.env.NODE_ENV === 'test' ? 'test-secret' : undefined)
        if (sessionSecret) {
          session.accessToken = await signJwtHS256(
            token as any,
            sessionSecret,
            30 * 24 * 60 * 60,
          )
        }
      }

      return session
    },
  },

  debug: nextAuthDebugEnabled,
}

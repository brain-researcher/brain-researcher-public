'use client'

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useSession, signOut } from 'next-auth/react'
import { getSupabaseClient, isSupabaseEnabled } from '@/lib/supabase/client'
import type { Session } from '@supabase/supabase-js'

const ACCESS_TOKEN_COOKIE = 'br_access_token'

type AuthProvider = 'supabase' | 'nextauth' | 'both'

const resolveAuthMode = (supabaseEnabled: boolean): AuthProvider => {
  const raw =
    process.env.NEXT_PUBLIC_AUTH_MODE ||
    process.env.NEXT_PUBLIC_BR_AUTH_PROVIDER ||
    ''
  const normalized = raw.trim().toLowerCase()
  if (normalized === 'supabase' || normalized === 'nextauth' || normalized === 'both') {
    return normalized as AuthProvider
  }
  return supabaseEnabled ? 'supabase' : 'nextauth'
}

function writeCookie(
  name: string,
  value: string,
  options: { path?: string; maxAgeSeconds?: number; sameSite?: 'Lax' | 'Strict' | 'None' } = {}
): void {
  if (typeof document === 'undefined') return
  const parts: string[] = [`${name}=${value}`]
  parts.push(`Path=${options.path ?? '/'}`)
  parts.push(`SameSite=${options.sameSite ?? 'Lax'}`)
  if (typeof options.maxAgeSeconds === 'number') {
    parts.push(`Max-Age=${Math.max(0, Math.floor(options.maxAgeSeconds))}`)
  }
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    parts.push('Secure')
  }
  document.cookie = parts.join('; ')
}

interface AuthSyncContextType {
  accessToken: string | null
  userId: string | null
  userRole: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
}

const AuthSyncContext = createContext<AuthSyncContextType>({
  accessToken: null,
  userId: null,
  userRole: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,
})

export function useAuthSync(): AuthSyncContextType {
  return useContext(AuthSyncContext)
}

interface AuthSyncProviderProps {
  children: React.ReactNode
}

export function AuthSyncProvider({ children }: AuthSyncProviderProps) {
  const { data: session, status } = useSession()
  const [supabaseSession, setSupabaseSession] = useState<Session | null>(null)
  const [supabaseLoading, setSupabaseLoading] = useState(false)
  const supabaseEnabled = isSupabaseEnabled()
  const requestedProvider = resolveAuthMode(supabaseEnabled)
  const authProvider: AuthProvider =
    !supabaseEnabled && requestedProvider !== 'nextauth' ? 'nextauth' : requestedProvider
  const usesSupabase = authProvider !== 'nextauth' && supabaseEnabled
  const usesNextAuth = authProvider !== 'supabase'
  const supabase = usesSupabase ? getSupabaseClient() : null

  // Handle session errors (e.g., token refresh failure)
  useEffect(() => {
    if (session?.error === 'RefreshAccessTokenError') {
      // Force sign out on token refresh error
      signOut({ callbackUrl: '/auth/login?error=session_expired' })
    }
  }, [session?.error])

  useEffect(() => {
    if (!usesSupabase || !supabase) return

    let cancelled = false
    setSupabaseLoading(true)
    supabase.auth.getSession().then(({ data }) => {
      if (!cancelled) {
        setSupabaseSession(data.session ?? null)
        setSupabaseLoading(false)
      }
    }).catch(() => {
      if (!cancelled) {
        setSupabaseLoading(false)
      }
    })

    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSupabaseSession(nextSession)
    })

    return () => {
      cancelled = true
      listener.subscription.unsubscribe()
    }
  }, [usesSupabase, supabase])

  // Mirror Supabase access token to a cookie so Next.js middleware can inject
  // `Authorization: Bearer ...` into `/api/*` requests.
  useEffect(() => {
    const supabaseToken = usesSupabase ? supabaseSession?.access_token || null : null
    const nextAuthToken = usesNextAuth ? ((session as any)?.accessToken as string | null) : null
    // In mixed mode, prefer the NextAuth HS256 token so backend services (Orchestrator/Agent)
    // can consistently validate the Authorization header.
    const token =
      authProvider === 'both'
        ? nextAuthToken || supabaseToken
        : supabaseToken || nextAuthToken

    if (!token) {
      writeCookie(ACCESS_TOKEN_COOKIE, '', { path: '/api', maxAgeSeconds: 0 })
      return
    }

    let maxAgeSeconds: number | undefined
    if (supabaseToken) {
      const expiresAt = supabaseSession?.expires_at
      const nowSec = Math.floor(Date.now() / 1000)
      maxAgeSeconds =
        typeof expiresAt === 'number' && Number.isFinite(expiresAt)
          ? Math.max(0, expiresAt - nowSec)
          : undefined
    } else if (session?.expires) {
      const expiresMs = Date.parse(session.expires)
      if (Number.isFinite(expiresMs)) {
        const nowMs = Date.now()
        maxAgeSeconds = Math.max(0, Math.floor((expiresMs - nowMs) / 1000))
      }
    }

    writeCookie(ACCESS_TOKEN_COOKIE, token, {
      path: '/api',
      maxAgeSeconds,
      sameSite: 'Lax',
    })
  }, [
    usesSupabase,
    usesNextAuth,
    supabaseSession?.access_token,
    supabaseSession?.expires_at,
    session?.expires,
    session?.accessToken,
  ])

  const contextValue = useMemo<AuthSyncContextType>(() => {
    const supabaseAccessToken = usesSupabase ? supabaseSession?.access_token || null : null
    const nextAuthAccessToken = usesNextAuth ? (session as any)?.accessToken || null : null
    const supabaseAuthenticated = Boolean(supabaseAccessToken)
    const nextAuthAuthenticated = status === 'authenticated' && !!nextAuthAccessToken
    const isAuthenticated = supabaseAuthenticated || nextAuthAuthenticated
    const isLoading =
      !isAuthenticated && ((usesSupabase && supabaseLoading) || (usesNextAuth && status === 'loading'))

    return {
      accessToken: supabaseAccessToken || nextAuthAccessToken,
      userId: supabaseAuthenticated ? supabaseSession?.user?.id || null : session?.user?.id || null,
      userRole: supabaseAuthenticated
        ? (supabaseSession?.user?.app_metadata?.role as string | undefined) || null
        : session?.user?.role || null,
      isAuthenticated,
      isLoading,
      error: usesNextAuth ? session?.error || null : null,
    }
  }, [session, status, supabaseSession, supabaseLoading, usesSupabase, usesNextAuth])

  return (
    <AuthSyncContext.Provider value={contextValue}>
      {children}
    </AuthSyncContext.Provider>
  )
}

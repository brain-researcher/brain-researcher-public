'use client'

import { useSession, signIn, signOut, getSession } from 'next-auth/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getSupabaseClient, isSupabaseEnabled } from '@/lib/supabase/client'
import type { Session } from '@supabase/supabase-js'

const E2E_AUTH_COOKIE = 'br_e2e_auth'

function hasE2EAuthCookie(): boolean {
  if (typeof document === 'undefined') return false
  return document.cookie
    .split(';')
    .some((part) => part.trim() === `${E2E_AUTH_COOKIE}=1`)
}

export interface AuthUser {
  id: string
  name: string | null
  email: string | null
  image?: string | null
  role?: string
  provider?: string
}

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

export interface UseAuthReturn {
  authProvider: AuthProvider
  oauthProviders: Array<'google' | 'github' | 'microsoft'>
  isAuthenticated: boolean
  isLoading: boolean
  user: AuthUser | null
  accessToken: string | null
  error: string | null
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>
  loginWithProvider: (provider: 'google' | 'github' | 'microsoft') => Promise<void>
  signup: (name: string, email: string, password: string) => Promise<{ success: boolean; error?: string }>
  logout: () => Promise<void>
  forgotPassword: (email: string) => Promise<{ success: boolean; error?: string }>
  sendMagicLink: (email: string) => Promise<{ success: boolean; error?: string }>
}

export function useAuth(): UseAuthReturn {
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
  // Avoid reading document.cookie during server render / first client render to prevent hydration mismatches.
  const [e2eCookieAuth, setE2ECookieAuth] = useState(false)

  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    setE2ECookieAuth(hasE2EAuthCookie())
  }, [])

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

  const supabaseAuthenticated = usesSupabase && Boolean(supabaseSession?.access_token)
  const nextAuthAuthenticated = status === 'authenticated' && !!session?.accessToken
  const isAuthenticated = e2eCookieAuth
    ? true
    : authProvider === 'both'
      ? supabaseAuthenticated || nextAuthAuthenticated
      : authProvider === 'supabase'
        ? supabaseAuthenticated
        : nextAuthAuthenticated
  const isLoading = e2eCookieAuth
    ? false
    : authProvider === 'both'
      ? !isAuthenticated && (supabaseLoading || status === 'loading')
      : authProvider === 'supabase'
        ? supabaseLoading
        : status === 'loading'
  const error = e2eCookieAuth ? null : authProvider === 'supabase' ? null : session?.error || null

  const user = useMemo<AuthUser | null>(() => {
    if (e2eCookieAuth) {
      return {
        id: 'e2e-user',
        name: 'E2E User',
        email: 'e2e@example.com',
        provider: 'e2e',
        role: 'e2e',
      }
    }
    const supaUser = usesSupabase ? supabaseSession?.user : null
    if (supaUser) {
      return {
        id: supaUser.id,
        name: (supaUser.user_metadata?.full_name as string | undefined) || null,
        email: supaUser.email || null,
        image: (supaUser.user_metadata?.avatar_url as string | undefined) || null,
        role: (supaUser.app_metadata?.role as string | undefined) || undefined,
        provider: (supaUser.app_metadata?.provider as string | undefined) || 'supabase',
      }
    }

    if (!session?.user) return null
    return {
      id: session.user.id || '',
      name: session.user.name || null,
      email: session.user.email || null,
      image: session.user.image,
      role: session.user.role,
      provider: session.user.provider,
    }
  }, [usesSupabase, e2eCookieAuth, session?.user, supabaseSession?.user])

  const accessToken = e2eCookieAuth
    ? 'e2e-access-token'
    : (usesSupabase ? supabaseSession?.access_token : null) || session?.accessToken || null

  const login = useCallback(async (email: string, password: string) => {
    const normalizedEmail = email.trim()
    let supabaseError: string | null = null
    let supabaseOk = false

    const tryNextAuthCredentials = async (): Promise<{ ok: boolean; error?: string }> => {
      try {
        const result = await signIn('credentials', {
          email: normalizedEmail,
          password,
          redirect: false,
        })

        if (!result || result.error) {
          return { ok: false, error: result?.error || 'Login failed' }
        }

        const sessionData = await getSession()
        if (!sessionData?.accessToken) {
          return { ok: false, error: 'Invalid credentials' }
        }

        return { ok: true }
      } catch (err: any) {
        return { ok: false, error: err?.message || 'Login failed' }
      }
    }

    const ensureOrchestratorUser = async (): Promise<void> => {
      // Backend requires a username (alphanumeric/underscore). Derive from email if possible.
      const usernameFromEmail =
        normalizedEmail.split('@')[0].replace(/[^a-zA-Z0-9_]/g, '_') || 'user'
      const username = usernameFromEmail.slice(0, 50)

      await fetch('/api/orchestrator/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          email: normalizedEmail,
          password,
          full_name: normalizedEmail.split('@')[0] || username,
          accept_terms: true,
        }),
      })
    }

    // Mixed mode: we must end up with a NextAuth HS256 session so Orchestrator can authenticate.
    if (authProvider === 'both' && usesNextAuth) {
      const nextAuthFirst = await tryNextAuthCredentials()
      if (nextAuthFirst.ok) return { success: true }

      if (usesSupabase) {
        if (!supabase) {
          supabaseError = 'Supabase is not configured'
        } else {
          const { error: signInError } = await supabase.auth.signInWithPassword({
            email: normalizedEmail,
            password,
          })
          if (!signInError) {
            supabaseOk = true
          } else {
            supabaseError = signInError.message
          }
        }
      }

      if (supabaseOk) {
        try {
          await ensureOrchestratorUser()
        } catch {
          // Ignore: user may already exist; we'll retry login either way.
        }

        const nextAuthRetry = await tryNextAuthCredentials()
        if (nextAuthRetry.ok) return { success: true }

        return {
          success: false,
          error:
            nextAuthRetry.error ||
            supabaseError ||
            'Signed in, but backend session could not be established',
        }
      }

      return {
        success: false,
        error: nextAuthFirst.error || supabaseError || 'Login failed',
      }
    }

    // Supabase-only mode
    if (usesSupabase && !usesNextAuth) {
      if (!supabase) return { success: false, error: 'Supabase is not configured' }
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: normalizedEmail,
        password,
      })
      if (!signInError) return { success: true }
      return { success: false, error: signInError.message || 'Login failed' }
    }

    // NextAuth-only mode (or fallback)
    if (!usesNextAuth) {
      return { success: false, error: supabaseError || 'Login failed' }
    }

    const nextAuth = await tryNextAuthCredentials()
    if (nextAuth.ok) return { success: true }
    return { success: false, error: nextAuth.error || 'Login failed' }
  }, [authProvider, supabase, usesSupabase, usesNextAuth])

  const loginWithProvider = useCallback(async (provider: 'google' | 'github' | 'microsoft') => {
    const nextAuthProvider = provider === 'microsoft' ? 'azure-ad' : provider

    // Prefer NextAuth in mixed mode so we get an HS256 session usable by Orchestrator.
    // OAuth providers require a full-page redirect (server-side 302 to the IdP),
    // so we must NOT pass `redirect: false` — that only works for credentials.
    if (usesNextAuth) {
      await signIn(nextAuthProvider, { callbackUrl: '/studio' })
      return
    }

    if (usesSupabase && supabase) {
      const mapped = provider === 'microsoft' ? 'azure' : provider
      await supabase.auth.signInWithOAuth({
        provider: mapped,
        options: { redirectTo: window.location.origin },
      })
    }
  }, [supabase, usesSupabase, usesNextAuth])

  const signup = useCallback(async (name: string, email: string, password: string) => {
    const normalizedEmail = email.trim()
    let supabaseSuccess = false
    let supabaseError: string | null = null

    if (usesSupabase) {
      if (!supabase) {
        supabaseError = 'Supabase is not configured'
      } else {
        const { error: signUpError } = await supabase.auth.signUp({
          email: normalizedEmail,
          password,
          options: {
            data: {
              full_name: name,
            },
          },
        })
        if (!signUpError) {
          supabaseSuccess = true
        } else {
          supabaseError = signUpError.message || 'Supabase signup failed'
        }
      }
    }

    if (!usesNextAuth) {
      return supabaseSuccess
        ? { success: true }
        : { success: false, error: supabaseError || 'Signup failed' }
    }

    let orchestratorSuccess = false
    let orchestratorError: string | null = null

    try {
      // Backend requires a username (alphanumeric/underscore). Derive from email if possible.
      const usernameFromEmail =
        normalizedEmail.split('@')[0].replace(/[^a-zA-Z0-9_]/g, '_') || 'user'
      const username = usernameFromEmail.slice(0, 50)

      // Call Orchestrator signup endpoint (real user store)
      const response = await fetch('/api/orchestrator/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          email: normalizedEmail,
          password,
          full_name: name,
          accept_terms: true,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        orchestratorError =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : errorData?.detail?.message || errorData?.detail?.error || 'Signup failed'
      } else {
        orchestratorSuccess = true

        // Then sign in with the new credentials
        const signInResult = await signIn('credentials', {
          email: normalizedEmail,
          password,
          redirect: false,
        })

        if (signInResult?.error) {
          orchestratorError = 'Account created but login failed'
          orchestratorSuccess = false
        }
      }
    } catch (error: any) {
      console.error('Signup error:', error)
      orchestratorError = error.message || 'Signup failed'
    }

    if (supabaseSuccess || orchestratorSuccess) {
      return { success: true }
    }

    return {
      success: false,
      error: orchestratorError || supabaseError || 'Signup failed',
    }
  }, [supabase, usesSupabase, usesNextAuth])

  const logout = useCallback(async () => {
    if (usesSupabase) {
      await supabase?.auth.signOut()
    }
    if (usesNextAuth) {
      await signOut({ callbackUrl: '/auth/login' })
    }
  }, [supabase, usesSupabase, usesNextAuth])

  const forgotPassword = useCallback(async (email: string) => {
    const normalizedEmail = email.trim()

    if (usesSupabase) {
      if (!supabase) {
        if (!usesNextAuth) {
          return { success: false, error: 'Supabase is not configured' }
        }
      } else {
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(normalizedEmail, {
          redirectTo: `${window.location.origin}/auth/login`,
        })
        if (!resetError) {
          return { success: true }
        }
        if (!usesNextAuth) {
          return { success: false, error: resetError.message }
        }
      }
    }
    try {
      const response = await fetch('/api/orchestrator/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ email: normalizedEmail }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        return {
          success: false,
          error: errorData.detail || 'Failed to send reset email'
        }
      }

      return { success: true }
    } catch (error: any) {
      console.error('Forgot password error:', error)
      return { success: false, error: error.message || 'Failed to send reset email' }
    }
  }, [supabase, usesSupabase, usesNextAuth])

  const sendMagicLink = useCallback(async (email: string) => {
    if (usesSupabase) {
      if (!supabase) {
        if (!usesNextAuth) {
          return { success: false, error: 'Supabase is not configured' }
        }
      } else {
        const { error: otpError } = await supabase.auth.signInWithOtp({
          email,
          options: {
            emailRedirectTo: window.location.origin,
          },
        })
        if (!otpError) {
          return { success: true }
        }
        if (!usesNextAuth) {
          return { success: false, error: otpError.message }
        }
      }
    }

    try {
      await signIn('email', {
        email,
        callbackUrl: '/',
        redirect: false,
      })
      return { success: true }
    } catch (error: any) {
      return { success: false, error: error.message || 'Failed to send magic link' }
    }
  }, [supabase, usesSupabase, usesNextAuth])

  return {
    authProvider,
    oauthProviders: ['google', 'github', 'microsoft'],
    isAuthenticated,
    isLoading,
    user,
    accessToken,
    error,
    login,
    loginWithProvider,
    signup,
    logout,
    forgotPassword,
    sendMagicLink,
  }
}

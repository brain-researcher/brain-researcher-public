'use client'

import { LoginForm } from '@/components/auth/login-form'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'

function sanitizeCallbackUrl(value: string | null): string | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!trimmed.startsWith('/')) return null
  // Avoid redirecting back into auth flows to prevent loops.
  if (trimmed.startsWith('/auth')) return null
  return trimmed
}

function deriveLoginNotice(callbackUrl: string | null): { title: string; description: string } | null {
  if (!callbackUrl) return null
  if (callbackUrl.startsWith('/vault')) {
    return {
      title: 'Login required for Vault',
      description: 'Sign in to access your datasets, analyses, and Result Packages.',
    }
  }
  if (callbackUrl.startsWith('/studio')) {
    return {
      title: 'Login required for Studio',
      description: 'Sign in to run analyses and generate Result Packages.',
    }
  }
  if (callbackUrl.startsWith('/settings')) {
    return {
      title: 'Login required',
      description: 'Sign in to access your account and settings.',
    }
  }
  return {
    title: 'Login required',
    description: 'Sign in to continue.',
  }
}

export default function LoginPage() {
  const { status } = useSession()
  const router = useRouter()
  const searchParams = useSearchParams()

  // Honor ?callbackUrl=... if present; otherwise send user to Studio.
  const callbackUrl = sanitizeCallbackUrl(searchParams?.get('callbackUrl')) || '/studio'
  const notice = deriveLoginNotice(callbackUrl)

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace(callbackUrl)
    }
  }, [callbackUrl, router, status])

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-md space-y-3">
        {notice ? (
          <Alert>
            <AlertTitle>{notice.title}</AlertTitle>
            <AlertDescription>
              {notice.description} After signing in, you’ll be redirected back.
            </AlertDescription>
          </Alert>
        ) : null}
        <LoginForm
          onForgotPassword={() => router.push('/auth/forgot')}
          onSignUp={() =>
            router.push(`/auth/signup?callbackUrl=${encodeURIComponent(callbackUrl)}`)
          }
          redirectTo={callbackUrl}
        />
      </div>
    </div>
  )
}

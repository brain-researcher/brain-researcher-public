'use client'

import { SignupForm, SignupFormData } from '@/components/auth/signup-form'
import { useAuth } from '@/hooks/use-auth'
import { useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'

function sanitizeCallbackUrl(value: string | null): string | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!trimmed.startsWith('/')) return null
  if (trimmed.startsWith('/auth')) return null
  return trimmed
}

export default function SignupPage() {
  const { signup } = useAuth()
  const { status } = useSession()
  const router = useRouter()
  const searchParams = useSearchParams()
  const callbackUrl =
    sanitizeCallbackUrl(searchParams?.get('callbackUrl')) || '/studio'

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace(callbackUrl)
    }
  }, [callbackUrl, router, status])

  const handleSubmit = async (data: SignupFormData) => {
    const result = await signup(
      `${data.firstName} ${data.lastName}`.trim(),
      data.email,
      data.password,
    )
    if ((result as any)?.success !== false) {
      router.push(callbackUrl)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 p-4">
      <SignupForm
        onSubmit={handleSubmit}
        onSignIn={() =>
          router.push(`/auth/login?callbackUrl=${encodeURIComponent(callbackUrl)}`)
        }
      />
    </div>
  )
}

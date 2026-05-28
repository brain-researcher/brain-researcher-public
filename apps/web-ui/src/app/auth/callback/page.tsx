'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { useSession } from 'next-auth/react'

const DEFAULT_REDIRECT = '/dashboard'

function OAuthCallbackContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const { status } = useSession()

  useEffect(() => {
    // NextAuth already handled the provider callback under /api/auth/callback.
    // We just route the user onward once the session is ready.
    if (status === 'authenticated') {
      const redirectParam = searchParams.get('redirect')
      const target = redirectParam && redirectParam.startsWith('/') ? redirectParam : DEFAULT_REDIRECT
      router.replace(target)
    }
    // If unauthenticated, let middleware/NextAuth drive sign-in.
  }, [router, searchParams, status])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800 px-4">
      <div className="max-w-md w-full bg-white dark:bg-gray-900 rounded-xl shadow-lg p-8 text-center space-y-6">
        <Loader2 className="mx-auto h-10 w-10 animate-spin text-blue-600" />
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Finishing sign-in
        </h1>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          We&apos;re completing your {searchParams.get('provider') || 'OAuth'} login.
        </p>
      </div>
    </div>
  )
}

function OAuthCallbackFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800 px-4">
      <div className="max-w-md w-full bg-white dark:bg-gray-900 rounded-xl shadow-lg p-8 text-center space-y-6">
        <Loader2 className="mx-auto h-10 w-10 animate-spin text-blue-600" />
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Preparing OAuth callback…
        </h1>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Sit tight while we finalize your sign-in.
        </p>
      </div>
    </div>
  )
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<OAuthCallbackFallback />}>
      <OAuthCallbackContent />
    </Suspense>
  )
}

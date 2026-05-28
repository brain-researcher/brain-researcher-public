'use client'

import Link from 'next/link'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/use-auth'

// The /analyses index has been retired in favour of the Studio Runs sidebar at
// /hub. Middleware (src/middleware.ts:renderAnalysesGone) emits a true HTTP 410
// with auth-branched HTML for production traffic. This page.tsx is kept as a
// safety net in case middleware is bypassed (e.g. when running tests that mount
// the route in isolation, or when middleware is disabled in a debug build).

export default function AnalysesGonePage() {
  const { isAuthenticated, isLoading } = useAuth()

  return (
    <NavigationWrapper>
      <main className="min-h-[calc(100dvh-4rem)] bg-gray-50">
        <div className="mx-auto flex max-w-2xl flex-col items-center justify-center px-4 py-16 text-center">
          <div className="rounded-2xl border border-slate-200 bg-white p-10 shadow-sm">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              Runs has moved into Studio
            </h1>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Open Studio to see your activity in the right sidebar. Each Studio
              session now ships with a Runs drawer that auto-refreshes and lets
              you attach a run into the open notebook with one click.
            </p>
            {!isLoading && !isAuthenticated ? (
              <p className="mt-3 text-sm text-slate-600">
                Sign in to see your runs in Studio.
              </p>
            ) : null}

            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              {isLoading ? (
                <span className="text-sm text-slate-500">
                  Checking your session…
                </span>
              ) : isAuthenticated ? (
                <Button asChild>
                  <Link href="/hub">Open Studio</Link>
                </Button>
              ) : (
                <Button asChild>
                  <Link href="/auth/login?callbackUrl=/hub">Sign in</Link>
                </Button>
              )}
              <Button asChild variant="outline">
                <Link href="/studio">Back to Studio chat</Link>
              </Button>
            </div>
          </div>
        </div>
      </main>
    </NavigationWrapper>
  )
}

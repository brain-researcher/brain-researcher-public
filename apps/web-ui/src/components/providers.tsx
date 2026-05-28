'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider as NextThemesProvider } from 'next-themes'
import { SessionProvider } from 'next-auth/react'
import { usePathname } from 'next/navigation'
import { useState } from 'react'
import { AuthSyncProvider } from '@/components/auth/auth-sync-provider'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { ErrorProvider } from '@/contexts/ErrorContext'
import { ErrorToastSystem } from '@/components/error/ErrorToastSystem'
import { AppErrorBoundary } from '@/components/error/GlobalErrorBoundary'
import { AccessibilityProvider } from '@/components/accessibility/AccessibilityProvider'
import FeedbackWidget from '@/components/feedback'
import { AnalyticsProvider } from '@/components/analytics/event-tracking'
import { Toaster } from '@/components/ui/toaster'

export function Providers({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isStudio = pathname?.startsWith('/studio') ?? false
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000, // 1 minute
        retry: 1,
      },
    },
  }))

  return (
    <AppErrorBoundary>
      <SessionProvider>
        <ErrorProvider
          maxErrors={25}
          enableAutoReport={true}
          onGlobalError={(error) => {
            // Log critical errors for monitoring
            if (error.severity === 'critical') {
              console.error('Critical application error:', error)
            }
          }}
        >
          <QueryClientProvider client={queryClient}>
            <AnalyticsProvider
              config={{
                apiEndpoint: '/api',
                trackingId: process.env.NEXT_PUBLIC_ANALYTICS_TRACKING_ID || 'local-dev',
                batchSize: 20,
                flushInterval: 10000,
              }}
            >
              <NextThemesProvider
                attribute="class"
                defaultTheme="light"
                enableSystem={false}
                disableTransitionOnChange
                forcedTheme="light"
              >
                <AccessibilityProvider>
                  <AuthSyncProvider>
                    <FeedbackProvider>
                      {children}
                      {process.env.NEXT_PUBLIC_ENABLE_FEEDBACK_WIDGET !== 'false' && !isStudio && (
                        <FeedbackWidget />
                      )}
                      <ErrorToastSystem position="top-right" maxToasts={4} />
                      <Toaster />
                    </FeedbackProvider>
                  </AuthSyncProvider>
                </AccessibilityProvider>
              </NextThemesProvider>
            </AnalyticsProvider>
          </QueryClientProvider>
        </ErrorProvider>
      </SessionProvider>
    </AppErrorBoundary>
  )
}

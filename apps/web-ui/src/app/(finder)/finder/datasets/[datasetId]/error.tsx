'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle, RefreshCw, Home, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function DatasetDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log error to error reporting service
    console.error('Dataset detail page error:', error)
  }, [error])

  return (
    <div className="mx-auto max-w-5xl py-6">
      <div className="mb-4">
        <Link href="/finder/datasets" className="text-sm text-primary hover:underline">
          &larr; Back to search
        </Link>
      </div>

      <div className="min-h-[400px] flex items-center justify-center">
        <div className="max-w-lg w-full text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-red-100 dark:bg-red-900/20 rounded-full mb-4">
            <AlertTriangle className="h-7 w-7 text-red-600 dark:text-red-400" />
          </div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
            Failed to load dataset
          </h2>
          <p className="text-gray-600 dark:text-gray-400 text-sm mb-4">
            An error occurred while loading the dataset details. Please try again.
          </p>

          {/* Error message */}
          <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6 text-left">
            <p className="text-sm text-red-800 dark:text-red-300 font-mono break-words">
              {error.message || 'Unknown error'}
            </p>
            {error.digest && (
              <p className="text-xs text-red-600/70 dark:text-red-400/70 mt-1">
                Error ID: {error.digest}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button onClick={reset} className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4" />
              Try Again
            </Button>
            <Button variant="outline" asChild className="flex items-center gap-2">
              <Link href="/finder/datasets">
                <ArrowLeft className="h-4 w-4" />
                Back to Search
              </Link>
            </Button>
            <Button variant="outline" asChild className="flex items-center gap-2">
              <Link href="/">
                <Home className="h-4 w-4" />
                Home
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

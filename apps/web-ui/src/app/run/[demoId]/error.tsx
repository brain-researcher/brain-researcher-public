'use client'

/**
 * Error boundary for run results page
 *
 * Catches and displays errors that occur during run loading
 */

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center">
        {/* Error icon */}
        <div className="mx-auto w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
          <svg
            className="w-8 h-8 text-red-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        {/* Error message */}
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Run Failed to Load
        </h2>
        <p className="text-gray-600 mb-6">
          {error.message || 'An unexpected error occurred while loading the run results.'}
        </p>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <button
            onClick={reset}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
          >
            Try Again
          </button>
          <a
            href="/"
            className="px-6 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors font-medium"
          >
            Back to Home
          </a>
        </div>

        {/* Technical details (only in development) */}
        {process.env.NODE_ENV === 'development' && error.digest && (
          <details className="mt-8 text-left">
            <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
              Technical Details
            </summary>
            <div className="mt-2 p-4 bg-gray-100 rounded text-xs font-mono text-gray-700 overflow-auto">
              <p className="mb-2">
                <strong>Error Digest:</strong> {error.digest}
              </p>
              <p>
                <strong>Stack:</strong>
              </p>
              <pre className="mt-1 whitespace-pre-wrap">{error.stack}</pre>
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

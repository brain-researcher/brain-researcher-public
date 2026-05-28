'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle } from 'lucide-react'

export default function Error({
    error,
    reset,
}: {
    error: Error & { digest?: string }
    reset: () => void
}) {
    useEffect(() => {
        console.error('Datasets page error:', error)
    }, [error])

    return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
            <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6 text-center">
                <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
                <h2 className="text-2xl font-bold mb-2">Unable to Load Datasets</h2>
                <p className="text-gray-600 mb-4">
                    {error.message || 'An unexpected error occurred while loading the dataset catalog.'}
                </p>
                <div className="flex gap-2 justify-center">
                    <Button onClick={reset} variant="default">
                        Try Again
                    </Button>
                    <Button onClick={() => window.location.href = '/dashboard'} variant="outline">
                        Go to Dashboard
                    </Button>
                </div>
                {process.env.NODE_ENV === 'development' && (
                    <pre className="mt-4 text-xs text-left bg-gray-100 p-3 rounded overflow-auto max-h-40">
                        {error.stack}
                    </pre>
                )}
            </div>
        </div>
    )
}

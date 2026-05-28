'use client'

import { AlertCircle, RefreshCw, Home } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

interface UnifiedErrorProps {
    title?: string
    message?: string
    error?: Error
    onRetry?: () => void
    showHomeButton?: boolean
}

export function UnifiedError({
    title = 'Something went wrong',
    message = 'An unexpected error occurred. Please try again.',
    error,
    onRetry,
    showHomeButton = true,
}: UnifiedErrorProps) {
    return (
        <div className="min-h-[400px] flex items-center justify-center p-4">
            <Card className="max-w-md w-full">
                <CardHeader className="text-center">
                    <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                        <AlertCircle className="h-6 w-6 text-red-600" />
                    </div>
                    <CardTitle>{title}</CardTitle>
                    <CardDescription>{message}</CardDescription>
                    {error && process.env.NODE_ENV === 'development' && (
                        <pre className="mt-2 text-xs text-left bg-gray-100 p-2 rounded overflow-auto max-h-32">
                            {error.message}
                        </pre>
                    )}
                </CardHeader>
                <CardContent className="flex gap-2 justify-center">
                    {onRetry && (
                        <Button onClick={onRetry} variant="default">
                            <RefreshCw className="mr-2 h-4 w-4" />
                            Try Again
                        </Button>
                    )}
                    {showHomeButton && (
                        <Button onClick={() => window.location.href = '/dashboard'} variant="outline">
                            <Home className="mr-2 h-4 w-4" />
                            Go to Dashboard
                        </Button>
                    )}
                </CardContent>
            </Card>
        </div>
    )
}

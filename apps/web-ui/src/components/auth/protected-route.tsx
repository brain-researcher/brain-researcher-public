'use client'

import React, { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/hooks/use-auth'
import { buildAuthLoginHref } from '@/lib/auth/login-redirect'

interface ProtectedRouteProps {
  children: React.ReactNode
  fallback?: React.ReactNode
  redirectTo?: string
  requireAuth?: boolean
}

export function ProtectedRoute({ 
  children, 
  fallback,
  redirectTo,
  requireAuth = true
}: ProtectedRouteProps) {
  const { isAuthenticated } = useAuth()
  const router = useRouter()
  const [isChecking, setIsChecking] = useState(true)

  useEffect(() => {
    // Allow some time for auth state to initialize
    const timer = setTimeout(() => {
      setIsChecking(false)
    }, 100)

    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (!isChecking) {
      if (requireAuth && !isAuthenticated) {
        // Store current path for redirect after login
        const currentPath = redirectTo || window.location.pathname + window.location.search
        const redirectUrl = buildAuthLoginHref(currentPath)
        router.push(redirectUrl)
      }
    }
  }, [isAuthenticated, isChecking, requireAuth, redirectTo, router])

  // Show loading state while checking auth
  if (isChecking) {
    return fallback || (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-2">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
          <span className="text-gray-600">Checking authentication...</span>
        </div>
      </div>
    )
  }

  // For routes that require authentication
  if (requireAuth && !isAuthenticated) {
    return fallback || null
  }

  // For routes that should redirect authenticated users (like login page)
  if (!requireAuth && isAuthenticated) {
    router.push('/dashboard')
    return null
  }

  return <>{children}</>
}

// Higher-order component version
export function withProtectedRoute<T extends {}>(
  WrappedComponent: React.ComponentType<T>,
  options: Omit<ProtectedRouteProps, 'children'> = {}
) {
  return function ProtectedComponent(props: T) {
    return (
      <ProtectedRoute {...options}>
        <WrappedComponent {...props} />
      </ProtectedRoute>
    )
  }
}

export default ProtectedRoute

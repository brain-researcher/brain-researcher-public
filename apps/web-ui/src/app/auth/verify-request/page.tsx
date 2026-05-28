'use client'

import { useEffect, useState } from 'react'
import { Mail, CheckCircle, Clock } from 'lucide-react'
import Link from 'next/link'

export default function VerifyRequestPage() {
  const [countdown, setCountdown] = useState(15 * 60) // 15 minutes in seconds
  
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 0) {
          clearInterval(timer)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    
    return () => clearInterval(timer)
  }, [])
  
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }
  
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div className="bg-white dark:bg-gray-800 shadow-xl rounded-2xl p-8">
          <div className="text-center">
            <div className="mx-auto flex items-center justify-center h-16 w-16 rounded-full bg-green-100 dark:bg-green-900 mb-4">
              <Mail className="h-8 w-8 text-green-600 dark:text-green-400" />
            </div>
            
            <h2 className="mt-4 text-2xl font-bold text-gray-900 dark:text-white">
              Check your email
            </h2>
            
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              We&apos;ve sent a login link to your email address. Click the link to sign in to your account.
            </p>
            
            <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/30 rounded-lg">
              <div className="flex items-center justify-center gap-2 text-blue-700 dark:text-blue-400">
                <Clock className="h-5 w-5" />
                <span className="font-semibold">Link expires in: {formatTime(countdown)}</span>
              </div>
            </div>
            
            <div className="mt-6 space-y-3">
              <div className="flex items-start gap-3 text-left">
                <CheckCircle className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  <p className="font-medium">Check your inbox</p>
                  <p>Look for an email from noreply@brain-researcher.ai</p>
                </div>
              </div>
              
              <div className="flex items-start gap-3 text-left">
                <CheckCircle className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  <p className="font-medium">Check spam folder</p>
                  <p>Sometimes our emails end up there</p>
                </div>
              </div>
              
              <div className="flex items-start gap-3 text-left">
                <CheckCircle className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  <p className="font-medium">Click the link</p>
                  <p>You&apos;ll be signed in automatically</p>
                </div>
              </div>
            </div>
            
            <div className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-700">
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                Didn&apos;t receive the email?
              </p>
              <Link
                href="/auth/signin"
                className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
              >
                Try again with a different method
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

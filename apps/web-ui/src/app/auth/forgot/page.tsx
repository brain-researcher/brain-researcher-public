'use client'

import { AuthenticationUI } from '@/components/auth/authentication-ui'

export default function ForgotPasswordPage() {
  return <AuthenticationUI mode="forgot" redirectUrl="/auth/login" />
}


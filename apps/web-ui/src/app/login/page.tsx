import { redirect } from 'next/navigation'

import { buildAuthLoginHref, sanitizeAuthCallbackUrl } from '@/lib/auth/login-redirect'

type LegacyLoginPageProps = {
  searchParams?: {
    redirect?: string
    callbackUrl?: string
  }
}

export default function LegacyLoginPage({ searchParams }: LegacyLoginPageProps) {
  const callbackUrl = sanitizeAuthCallbackUrl(
    searchParams?.callbackUrl ?? searchParams?.redirect,
  )
  redirect(buildAuthLoginHref(callbackUrl))
}

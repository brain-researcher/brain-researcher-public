'use client'

import Link from 'next/link'

import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

type AdvancedViewBannerProps = {
  canonicalHref: string
  message?: string
  className?: string
}

export function AdvancedViewBanner({
  canonicalHref,
  message,
  className,
}: AdvancedViewBannerProps) {
  const { allowed, enabled, setEnabled } = useAdvancedMode()

  return (
    <Alert variant="warning" className={className}>
      <AlertTitle>Advanced view</AlertTitle>
      <AlertDescription>
        <p>
          {message ??
            'This page exposes internal system details. Most users should use Studio (create) and Vault (results) instead.'}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" asChild>
            <Link href={canonicalHref}>Go to the standard view</Link>
          </Button>
          {allowed && !enabled ? (
            <Button size="sm" variant="outline" onClick={() => setEnabled(true)}>
              Enable Advanced Mode
            </Button>
          ) : null}
          <Button size="sm" variant="outline" asChild>
            <Link href="/settings">Settings</Link>
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  )
}

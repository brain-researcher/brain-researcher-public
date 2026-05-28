'use client'

import { AuthenticatedNavigation } from '@/components/authenticated-navigation'
import { NavigationHeader } from '@/components/navigation/navigation-header'
import { useAuth } from '@/hooks/use-auth'
import clsx from 'clsx'
import { usePathname } from 'next/navigation'

interface NavigationWrapperProps {
  children?: React.ReactNode
}

export function NavigationWrapper({ children }: NavigationWrapperProps) {
  const { isAuthenticated } = useAuth()
  const pathname = usePathname()

  const headerClass = clsx(
    'sticky top-0 z-40 bg-white/90 backdrop-blur-md border-b border-slate-200',
    'shadow-sm'
  )

  return (
    <>
      {isAuthenticated ? (
        <div className={headerClass}>
          <AuthenticatedNavigation />
        </div>
      ) : (
        <div className={headerClass}>
          <NavigationHeader
            user={null}
            showSearch={true}
            showConnectionStatus={pathname !== '/'}
          />
        </div>
      )}
      <div className="pt-16">
        {children}
      </div>
    </>
  )
}

'use client'

import { useAuth } from '@/hooks/use-auth'
import { NavigationHeader } from '@/components/navigation/navigation-header'
import { useRouter } from 'next/navigation'

export function AuthenticatedNavigation() {
  const { user, logout } = useAuth()
  const router = useRouter()

  const handleLogout = async () => {
    await logout()
    router.push('/auth/login')
  }

  // Format user data for NavigationHeader (name and email are required strings)
  const formattedUser = user ? {
    name: user.name || 'User',
    email: user.email || '',
    avatar: user.image || undefined
  } : null

  return (
    <NavigationHeader
      user={formattedUser}
      onLogout={handleLogout}
    />
  )
}

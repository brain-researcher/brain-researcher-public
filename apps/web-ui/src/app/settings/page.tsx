'use client'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { SettingsInterface } from '@/components/settings/SettingsInterface'

export default function SettingsPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto p-6">
          <SettingsInterface />
        </div>
      </div>
    </NavigationWrapper>
  )
}
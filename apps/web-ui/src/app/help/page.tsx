'use client'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { HelpSystem } from '@/components/help/HelpSystem'

export default function HelpPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto p-6">
          <HelpSystem />
        </div>
      </div>
    </NavigationWrapper>
  )
}
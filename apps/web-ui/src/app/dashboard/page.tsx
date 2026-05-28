import { LinearDashboard } from '@/components/dashboard/LinearDashboard'
import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

export default function DashboardPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <AdvancedViewBanner canonicalHref="/studio" />
          <LinearDashboard />
        </div>
      </div>
    </NavigationWrapper>
  )
}

export const dynamic = 'force-dynamic'

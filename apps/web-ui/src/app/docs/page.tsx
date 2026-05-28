// Docs landing page with Linear style navigation
import Link from 'next/link'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

export default function DocsPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-3xl mx-auto py-8 px-4">
          <h1 className="text-3xl font-bold mb-4">Documentation</h1>
          <p className="text-gray-600 mb-6">
            Welcome to the Brain Researcher docs. Choose a section to get started.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Link href="/help" className="block border rounded-lg p-4 hover:bg-gray-50 bg-white transition-colors">
              <h2 className="font-semibold mb-1">Help Center</h2>
              <p className="text-sm text-gray-600">FAQs, troubleshooting, and guides</p>
            </Link>

            <Link href="/dashboard?view=resources" className="block border rounded-lg p-4 hover:bg-gray-50 bg-white transition-colors">
              <h2 className="font-semibold mb-1">Resources</h2>
              <p className="text-sm text-gray-600">System status and performance</p>
            </Link>

            <Link href="/dashboard?view=analytics" className="block border rounded-lg p-4 hover:bg-gray-50 bg-white transition-colors">
              <h2 className="font-semibold mb-1">Analytics</h2>
              <p className="text-sm text-gray-600">Usage and performance metrics</p>
            </Link>

            <Link href="/dashboard" className="block border rounded-lg p-4 hover:bg-gray-50 bg-white transition-colors">
              <h2 className="font-semibold mb-1">Dashboard</h2>
              <p className="text-sm text-gray-600">Overview of your workspace</p>
            </Link>
          </div>
        </div>
      </div>
    </NavigationWrapper>
  )
}

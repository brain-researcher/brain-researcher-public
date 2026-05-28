import Link from 'next/link'
import { Brain } from 'lucide-react'

export function NavigationLinear() {
  return (
    <header className="sticky top-0 z-50 w-full border-b bg-white/80 backdrop-blur">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-14 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 shadow-sm">
              <Brain className="h-5 w-5 text-white" />
            </div>
            <span className="font-semibold text-gray-900">Brain Researcher</span>
          </Link>

          {/* Navigation */}
          <nav className="flex items-center gap-6">
            <Link 
              href="/chat" 
              className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
            >
              Chat
            </Link>
            <Link 
              href="/datasets" 
              className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
            >
              Datasets
            </Link>
            <Link
              href="/dashboard"
              className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
            >
              Dashboard
            </Link>
            <Link
              href="/kg"
              className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
            >
              Knowledge Graph
            </Link>
            <Link
              href="/datasets"
              className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
            >
              Finder
            </Link>
          </nav>
        </div>
      </div>
    </header>
  )
}

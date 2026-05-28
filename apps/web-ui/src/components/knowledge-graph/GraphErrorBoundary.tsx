'use client'

import React, { Component, ErrorInfo, ReactNode } from 'react'
import { Network } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

export class GraphErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Graph visualization error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-[600px] bg-gradient-to-br from-red-50 to-red-100 rounded-lg flex items-center justify-center">
          <div className="text-center p-6 bg-white border border-red-200 rounded-lg max-w-md">
            <Network className="h-10 w-10 text-red-400 mx-auto mb-2" />
            <div className="font-semibold mb-1">Graph Visualization Error</div>
            <div className="text-sm text-gray-600 mb-3">
              The graph visualization encountered an error and cannot be displayed.
            </div>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm"
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

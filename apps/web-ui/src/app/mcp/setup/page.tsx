'use client'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { McpConfigurationPanel } from '@/components/mcp/mcp-configuration-panel'
import { McpSetupGuide } from '@/components/mcp/mcp-setup-guide'

export default function McpSetupPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-gray-900">Run Brain Researcher with MCP</h1>
            <p className="text-sm text-muted-foreground">
              Brain Researcher hands workflows off to whatever coding agent you already use.
              Configure your client once below, then hand off from any workflow, dataset, or KG view.
            </p>
          </div>
          <McpConfigurationPanel />
          <McpSetupGuide />
        </div>
      </div>
    </NavigationWrapper>
  )
}

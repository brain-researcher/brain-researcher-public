'use client'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { McpConfigurationPanel } from '@/components/mcp/mcp-configuration-panel'
import { McpSetupGuide } from '@/components/mcp/mcp-setup-guide'

export default function McpSetupPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-gray-900">
              Connect Brain Researcher to your coding agent
            </h1>
            <p className="text-sm text-muted-foreground">
              Four steps: <span className="text-gray-900">1)</span> generate a personal token,{' '}
              <span className="text-gray-900">2)</span> paste the config into Cursor, Codex, or
              Claude Code, <span className="text-gray-900">3)</span> verify the connection, then{' '}
              <span className="text-gray-900">4)</span> hand off a workflow. After setup you can
              hand off from any workflow, dataset, or KG view.
            </p>
          </div>
          <McpConfigurationPanel numbered />
          <McpSetupGuide />
        </div>
      </div>
    </NavigationWrapper>
  )
}

import Link from 'next/link'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { GitBranch, Layers } from 'lucide-react'

export default function WorkflowPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <AdvancedViewBanner canonicalHref="/studio" />
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">Workflow</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Build pipelines, run jobs, and monitor executions.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GitBranch className="h-5 w-5 text-blue-600" />
                  Pipeline Builder
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Assemble a custom pipeline graph and launch it as a job.
                </p>
                <Button asChild>
                  <Link href="/pipeline-builder">Open Pipeline Builder</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Layers className="h-5 w-5 text-purple-600" />
                  Pipeline Management
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Monitor active jobs, inspect node graphs, and review queue health.
                </p>
                <Button asChild variant="outline">
                  <Link href="/pipeline">View Pipeline Runs</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </NavigationWrapper>
  )
}

export const dynamic = 'force-dynamic'

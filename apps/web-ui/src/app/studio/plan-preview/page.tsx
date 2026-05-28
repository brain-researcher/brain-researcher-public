import Link from 'next/link'

import { StudioPlanPanelExample } from '@/components/chat/plan/studio-plan-panel-example'
import { Button } from '@/components/ui/button'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

export default function StudioPlanPreviewPage() {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-10 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xl font-semibold text-foreground">Studio notebook preview</div>
              <div className="text-sm text-muted-foreground">
                Preview of a notebook-style Studio: execution stays in the main stream, and the
                right rail stays focused on the selected artifact.
              </div>
            </div>
            <Button variant="outline" asChild>
              <Link href="/studio?tab=plan">Back to live studio</Link>
            </Button>
            <Button asChild>
              <Link href="/settings?tab=integrations&handoff=coding-agent&workflowId=workflow_rest_connectome_e2e&datasetId=ds000114">
                Get MCP recipe
              </Link>
            </Button>
          </div>

          <StudioPlanPanelExample />
        </div>
      </div>
    </NavigationWrapper>
  )
}

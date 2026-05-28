import { describe, expect, it } from 'vitest'

import { buildCodingAgentHandoffHref } from '@/lib/coding-agent-handoff'

describe('buildCodingAgentHandoffHref', () => {
  it('opens MCP integrations with workflow and dataset handoff context', () => {
    const href = buildCodingAgentHandoffHref({
      datasetId: 'ds000114',
      datasetVersion: '1.0.1',
      workflowId: 'workflow_rest_connectome_e2e',
      workflowLabel: 'Atlas-Based Signal Extraction',
      threadId: 'thread_abc',
    })

    expect(href).toBe(
      '/settings?tab=integrations&handoff=coding-agent&datasetId=ds000114&datasetVersion=1.0.1&workflowId=workflow_rest_connectome_e2e&workflowLabel=Atlas-Based+Signal+Extraction&threadId=thread_abc',
    )
  })

  it('omits empty optional fields', () => {
    expect(buildCodingAgentHandoffHref({ workflowId: 'workflow_mriqc', datasetId: ' ' })).toBe(
      '/settings?tab=integrations&handoff=coding-agent&workflowId=workflow_mriqc',
    )
  })
})

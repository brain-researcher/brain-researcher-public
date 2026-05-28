// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/components/navigation/navigation-wrapper', () => ({
  NavigationWrapper: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import StudioPlanPreviewPage from './page'

describe('StudioPlanPreviewPage', () => {
  it('renders the preview route as a notebook-style studio example', () => {
    render(<StudioPlanPreviewPage />)

    expect(screen.getByText('Studio notebook preview')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Preview of a notebook-style Studio: execution stays in the main stream, and the right rail stays focused on the selected artifact.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to live studio' })).toHaveAttribute(
      'href',
      '/studio?tab=plan',
    )
    expect(screen.getByRole('link', { name: 'Get MCP recipe' })).toHaveAttribute(
      'href',
      expect.stringContaining('workflowId=workflow_rest_connectome_e2e'),
    )
  })
})

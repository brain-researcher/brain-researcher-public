import { describe, expect, it } from 'vitest'

import { primaryNavItems } from '../navigation-items'

describe('primary navigation ordering', () => {
  it('keeps MCP leftmost and Studio on the right edge of the primary panel', () => {
    expect(primaryNavItems.map((item) => item.label)).toEqual([
      'MCP',
      'Datasets',
      'Workflows',
      'Demos',
      'Knowledge Graph',
      'Studio',
    ])
    expect(primaryNavItems[0]).toMatchObject({ label: 'MCP', href: '/mcp/setup' })
    expect(primaryNavItems.at(-1)).toMatchObject({ label: 'Studio', href: '/hub' })
  })
})

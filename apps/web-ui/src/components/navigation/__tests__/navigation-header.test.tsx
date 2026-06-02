// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { NavigationHeader } from '../navigation-header'

// Isolate the header: stub the heavy children + data hooks so these tests focus
// on the header's own chrome and palette.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/datasets',
}))
vi.mock('@/components/status/ConnectionStatus', () => ({
  ConnectionStatus: () => null,
}))
vi.mock('@/components/help', () => ({ HelpSystem: () => null }))
vi.mock('@/components/workspace/workspace-switcher', () => ({
  WorkspaceSwitcher: () => null,
}))
vi.mock('@/hooks/use-advanced-mode', () => ({
  useAdvancedMode: () => ({ enabled: false }),
}))

const USER = { name: 'Ada', email: 'ada@example.com' }

describe('NavigationHeader (search removed)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders no search region for unauthenticated users', () => {
    render(<NavigationHeader user={null} />)
    expect(screen.queryAllByRole('search')).toHaveLength(0)
  })

  it('renders no search region for authenticated users', () => {
    render(<NavigationHeader user={USER} />)
    expect(screen.queryAllByRole('search')).toHaveLength(0)
  })
})

describe('NavigationHeader palette (Track C)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses no blue accent classes in the nav chrome', () => {
    const { container } = render(<NavigationHeader user={USER} />)
    expect(container.innerHTML).not.toMatch(/blue-\d/)
  })

  it('renders the logo wordmark in the neutral primary color', () => {
    const { container } = render(<NavigationHeader user={USER} />)
    // The Brain logo + wordmark use the neutral primary (gray-900 / white).
    expect(container.innerHTML).toMatch(/text-gray-900/)
  })
})

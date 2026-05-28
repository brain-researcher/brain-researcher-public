import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

// Mock the viewers
vi.mock('../viewers/BrainMapViewer', () => ({
  BrainMapViewer: ({ item }: any) => <div data-testid="brain-map-viewer">{item.name}</div>
}))

vi.mock('../viewers/TableViewer', () => ({
  TableViewer: ({ item }: any) => <div data-testid="table-viewer">{item.name}</div>
}))

vi.mock('../viewers/GraphViewer', () => ({
  GraphViewer: ({ item }: any) => <div data-testid="graph-viewer">{item.name}</div>
}))

vi.mock('../viewers/ReportViewer', () => ({
  ReportViewer: ({ item }: any) => <div data-testid="report-viewer">{item.name}</div>
}))

import { Lightbox } from '../Lightbox'

const mockItems = [
  {
    id: '1',
    name: 'Brain Map 1',
    description: 'First brain map',
    type: 'brain-map' as const,
    thumbnail: '/thumb1.jpg',
    fullUrl: '/brain1.nii.gz',
    fileSize: 1024000,
    mimeType: 'application/x-nifti',
    created: new Date('2024-01-01'),
    modified: new Date('2024-01-02'),
    analysis: {
      type: 'GLM',
      pipeline: 'fMRIPrep',
      duration: 300,
      status: 'completed' as const
    },
    metadata: {
      dimensions: [64, 64, 30],
      voxelSize: [3, 3, 3],
      format: 'NIfTI'
    },
    tags: ['contrast', 'task-faces'],
    annotations: 'Main effect of faces vs baseline'
  },
  {
    id: '2',
    name: 'Results Table',
    description: 'Statistical results',
    type: 'table' as const,
    thumbnail: '/thumb2.jpg',
    fullUrl: '/results.csv',
    fileSize: 50000,
    mimeType: 'text/csv',
    created: new Date('2024-01-03'),
    modified: new Date('2024-01-04'),
    analysis: {
      type: 'Statistical',
      pipeline: 'Custom',
      duration: 60,
      status: 'completed' as const
    },
    metadata: {
      rows: 1000,
      columns: 5,
      format: 'CSV'
    },
    tags: ['statistics', 'peaks']
  }
]

describe('Lightbox', () => {
  const mockProps = {
    items: mockItems,
    currentIndex: 0,
    onClose: vi.fn(),
    onNavigate: vi.fn(),
    onDownload: vi.fn(),
    onShare: vi.fn()
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Basic Rendering', () => {
    it('renders lightbox with current item', () => {
      render(<Lightbox {...mockProps} />)
      
      expect(screen.getByRole('heading', { level: 2, name: 'Brain Map 1' })).toBeInTheDocument()
      expect(screen.getByText('1 of 2')).toBeInTheDocument()
    })

    it('renders appropriate viewer for item type', () => {
      render(<Lightbox {...mockProps} />)
      
      expect(screen.getByTestId('brain-map-viewer')).toBeInTheDocument()
      expect(screen.getByTestId('brain-map-viewer')).toHaveTextContent('Brain Map 1')
    })

    it('renders different viewer for different item types', () => {
      render(<Lightbox {...mockProps} currentIndex={1} />)
      
      expect(screen.getByTestId('table-viewer')).toBeInTheDocument()
      expect(screen.getByTestId('table-viewer')).toHaveTextContent('Results Table')
    })
  })

  describe('Navigation', () => {
    it('navigates to next item', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const nextButton = screen.getByTitle('Next')
      await user.click(nextButton)
      expect(mockProps.onNavigate).toHaveBeenCalledWith(1)
    })

    it('navigates to previous item', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} currentIndex={1} />)
      
      const prevButton = screen.getByTitle('Previous')
      await user.click(prevButton)
      expect(mockProps.onNavigate).toHaveBeenCalledWith(0)
    })

    it('disables navigation buttons at boundaries', () => {
      const { rerender } = render(<Lightbox {...mockProps} currentIndex={0} />)
      
      const prevButton = screen.getByTitle('Previous')
      expect(prevButton).toBeDisabled()

      rerender(<Lightbox {...mockProps} currentIndex={1} />)
      
      const nextButton = screen.getByTitle('Next')
      expect(nextButton).toBeDisabled()
    })
  })

  describe('Keyboard Shortcuts', () => {
    it('closes on Escape key', () => {
      render(<Lightbox {...mockProps} />)
      
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(mockProps.onClose).toHaveBeenCalled()
    })

    it('navigates with arrow keys', () => {
      const { rerender } = render(<Lightbox {...mockProps} />)

      fireEvent.keyDown(window, { key: 'ArrowRight' })
      expect(mockProps.onNavigate).toHaveBeenCalledWith(1)
      
      rerender(<Lightbox {...mockProps} currentIndex={1} />)
      fireEvent.keyDown(window, { key: 'ArrowLeft' })
      expect(mockProps.onNavigate).toHaveBeenCalledWith(0)
    })

    it('toggles info panel with i key', () => {
      render(<Lightbox {...mockProps} />)
      
      fireEvent.keyDown(window, { key: 'i' })
      
      // Should show info panel
      expect(screen.getByText('Item Details')).toBeInTheDocument()
    })

    it('toggles fullscreen with f key', () => {
      render(<Lightbox {...mockProps} />)
      
      fireEvent.keyDown(window, { key: 'f' })
      
      // Component should be in fullscreen mode (implementation specific)
    })

    it('toggles comparison with c key when enabled', () => {
      const onToggleComparison = vi.fn()
      render(
        <Lightbox 
          {...mockProps} 
          enableComparison={true}
          onToggleComparison={onToggleComparison}
        />
      )
      
      fireEvent.keyDown(window, { key: 'c' })
      expect(onToggleComparison).toHaveBeenCalled()
    })
  })

  describe('Info Panel', () => {
    it('toggles info panel visibility', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const infoButton = screen.getByTitle('Toggle info (i)')
      
      // Info panel should not be visible initially
      expect(screen.queryByText('Item Details')).not.toBeInTheDocument()
      
      await user.click(infoButton)
      
      // Should show info panel
      expect(screen.getByText('Item Details')).toBeInTheDocument()
    })

    it('displays item information in info panel', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const infoButton = screen.getByTitle('Toggle info (i)')
      await user.click(infoButton)
      
      // Should show various item details
      expect(screen.getByText('Basic Information')).toBeInTheDocument()
      expect(screen.getByText('Analysis Details')).toBeInTheDocument()
      expect(screen.getAllByText('Brain Map 1').length).toBeGreaterThan(0)
      expect(screen.getByText('brain-map')).toBeInTheDocument()
      expect(screen.getByText('GLM')).toBeInTheDocument()
    })

    it('shows tags when available', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const infoButton = screen.getByTitle('Toggle info (i)')
      await user.click(infoButton)
      
      expect(screen.getByText('contrast')).toBeInTheDocument()
      expect(screen.getByText('task-faces')).toBeInTheDocument()
    })

    it('copies item info to clipboard', async () => {
      const user = userEvent.setup()
      const mockClipboard = {
        writeText: vi.fn().mockResolvedValue(undefined)
      }
      Object.defineProperty(navigator, 'clipboard', {
        value: mockClipboard,
        configurable: true
      })
      
      render(<Lightbox {...mockProps} />)
      
      const infoButton = screen.getByTitle('Toggle info (i)')
      await user.click(infoButton)
      
      const copyButton = screen.getByTitle('Copy info as JSON')
      await user.click(copyButton)
      
      expect(mockClipboard.writeText).toHaveBeenCalled()
    })
  })

  describe('Comparison Mode', () => {
    const comparisonItems = [mockItems[0], mockItems[1]]
    
    it('shows comparison mode when enabled and items provided', () => {
      render(
        <Lightbox 
          {...mockProps} 
          enableComparison={true}
          comparisonItems={comparisonItems}
          showComparison={true}
        />
      )
      
      expect(screen.getByText('Comparing 2 items')).toBeInTheDocument()
    })

    it('renders multiple viewers in comparison mode', () => {
      render(
        <Lightbox 
          {...mockProps} 
          enableComparison={true}
          comparisonItems={comparisonItems}
          showComparison={true}
        />
      )
      
      expect(screen.getByTestId('brain-map-viewer')).toBeInTheDocument()
      expect(screen.getByTestId('table-viewer')).toBeInTheDocument()
    })

    it('shows item names in comparison mode', () => {
      render(
        <Lightbox 
          {...mockProps} 
          enableComparison={true}
          comparisonItems={comparisonItems}
          showComparison={true}
        />
      )
      
      // Should show both item names as overlays
      const brainMapText = screen.getAllByText('Brain Map 1')
      const tableText = screen.getAllByText('Results Table')
      
      expect(brainMapText.length).toBeGreaterThan(0)
      expect(tableText.length).toBeGreaterThan(0)
    })
  })

  describe('Actions', () => {
    it('calls onClose when close button is clicked', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const closeButton = screen.getByTitle('Close (Esc)')
      await user.click(closeButton)
      
      expect(mockProps.onClose).toHaveBeenCalled()
    })

    it('calls onDownload when download button is clicked', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const downloadButton = screen.getByTitle('Download')
      await user.click(downloadButton)
      
      expect(mockProps.onDownload).toHaveBeenCalledWith(mockItems[0])
    })

    it('calls onShare when share button is clicked', async () => {
      const user = userEvent.setup()
      render(<Lightbox {...mockProps} />)
      
      const shareButton = screen.getByTitle('Share')
      await user.click(shareButton)
      
      expect(mockProps.onShare).toHaveBeenCalledWith(mockItems[0])
    })

    it('toggles fullscreen mode', async () => {
      const user = userEvent.setup()
      const { container } = render(<Lightbox {...mockProps} />)
      
      const fullscreenButton = screen.getByTitle('Toggle fullscreen (f)')
      await user.click(fullscreenButton)
      
      // Should add fullscreen classes (implementation specific)
      const lightboxContainer = container.firstChild as HTMLElement
      expect(lightboxContainer).toHaveClass('p-0')
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels and roles', () => {
      render(<Lightbox {...mockProps} />)
      
      const buttons = screen.getAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
      
      // All buttons should have accessible names
      buttons.forEach(button => {
        expect(button).toHaveAttribute('title')
      })
    })

    it('shows keyboard shortcuts help', () => {
      render(<Lightbox {...mockProps} />)
      
      expect(screen.getByText('Navigate')).toBeInTheDocument()
      expect(screen.getByText('Close')).toBeInTheDocument()
      expect(screen.getByText('Info')).toBeInTheDocument()
      expect(screen.getByText('Fullscreen')).toBeInTheDocument()
    })

    it('shows comparison shortcut when enabled', () => {
      render(
        <Lightbox 
          {...mockProps} 
          enableComparison={true}
        />
      )
      
      expect(screen.getByText('Compare')).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('handles missing viewer gracefully', () => {
      const itemWithUnknownType = {
        ...mockItems[0],
        type: 'unknown' as any
      }
      
      render(<Lightbox {...mockProps} items={[itemWithUnknownType]} />)
      
      // Should render fallback viewer
      expect(screen.getByRole('heading', { level: 3, name: 'Brain Map 1' })).toBeInTheDocument()
    })

    it('handles navigation beyond bounds', () => {
      render(<Lightbox {...mockProps} currentIndex={0} />)
      
      fireEvent.keyDown(window, { key: 'ArrowLeft' })
      
      // Should not navigate beyond first item
      expect(mockProps.onNavigate).not.toHaveBeenCalledWith(-1)
    })
  })

  describe('Performance', () => {
    it('does not render unnecessary components', () => {
      render(<Lightbox {...mockProps} />)
      
      // Should only render one viewer at a time (unless in comparison mode)
      expect(screen.getByTestId('brain-map-viewer')).toBeInTheDocument()
      expect(screen.queryByTestId('table-viewer')).not.toBeInTheDocument()
    })

    it('efficiently updates when currentIndex changes', () => {
      const { rerender } = render(<Lightbox {...mockProps} currentIndex={0} />)
      
      expect(screen.getByTestId('brain-map-viewer')).toBeInTheDocument()
      
      rerender(<Lightbox {...mockProps} currentIndex={1} />)
      
      expect(screen.getByTestId('table-viewer')).toBeInTheDocument()
      expect(screen.queryByTestId('brain-map-viewer')).not.toBeInTheDocument()
    })
  })
})

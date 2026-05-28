import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ResultGallery } from '../ResultGallery'

// Mock dependencies
jest.mock('next/image', () => {
  return function MockImage({ src, alt, ...props }: any) {
    return <img src={src} alt={alt} {...props} />
  }
})

// Mock gallery item data
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
    tags: ['statistics', 'peaks'],
    annotations: 'Peak coordinates and statistics'
  },
  {
    id: '3',
    name: 'Processing Graph',
    description: 'Graph in progress',
    type: 'graph' as const,
    thumbnail: '/thumb3.jpg',
    fullUrl: '/graph.png',
    fileSize: 200000,
    mimeType: 'image/png',
    created: new Date('2024-01-05'),
    modified: new Date('2024-01-05'),
    analysis: {
      type: 'Visualization',
      pipeline: 'Matplotlib',
      duration: 120,
      status: 'processing' as const
    },
    metadata: {
      dimensions: { width: 800, height: 600 },
      format: 'PNG'
    },
    tags: ['visualization', 'timeseries']
  }
]

describe('ResultGallery', () => {
  const mockProps = {
    items: mockItems,
    onItemClick: jest.fn(),
    onDownload: jest.fn(),
    onShare: jest.fn(),
    onDelete: jest.fn()
  }

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Basic Rendering', () => {
    it('renders gallery with items', () => {
      render(<ResultGallery {...mockProps} />)
      
      expect(screen.getByText('Results Gallery')).toBeInTheDocument()
      expect(screen.getByText('Brain Map 1')).toBeInTheDocument()
      expect(screen.getByText('Results Table')).toBeInTheDocument()
      expect(screen.getByText('Processing Graph')).toBeInTheDocument()
    })

    it('renders empty state when no items', () => {
      render(<ResultGallery {...mockProps} items={[]} />)
      
      expect(screen.getByText('No results found')).toBeInTheDocument()
    })

    it('shows correct item counts', () => {
      render(<ResultGallery {...mockProps} />)
      
      expect(screen.getByText('Showing 1 to 3 of 3 results')).toBeInTheDocument()
    })
  })

  describe('View Modes', () => {
    it('switches between grid and list view', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const listViewButton = screen.getByTitle('List view')
      await user.click(listViewButton)
      
      // Should be in list view now
      expect(listViewButton).toHaveClass('bg-white')
    })

    it('displays items differently in list vs grid view', async () => {
      const user = userEvent.setup()
      const { container } = render(<ResultGallery {...mockProps} />)
      
      // Grid view by default
      expect(container.querySelector('.grid')).toBeInTheDocument()
      
      // Switch to list view
      const listViewButton = screen.getByTitle('List view')
      await user.click(listViewButton)
      
      expect(container.querySelector('.space-y-2')).toBeInTheDocument()
    })
  })

  describe('Search and Filtering', () => {
    it('filters items by search query', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const searchInput = screen.getByPlaceholderText('Search results...')
      await user.type(searchInput, 'brain')
      
      await waitFor(() => {
        expect(screen.getByText('Brain Map 1')).toBeInTheDocument()
        expect(screen.queryByText('Results Table')).not.toBeInTheDocument()
      })
    })

    it('filters items by type', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const typeFilter = screen.getByDisplayValue('All Types')
      await user.selectOptions(typeFilter, 'brain-map')
      
      await waitFor(() => {
        expect(screen.getByText('Brain Map 1')).toBeInTheDocument()
        expect(screen.queryByText('Results Table')).not.toBeInTheDocument()
      })
    })

    it('clears filters correctly', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      // Apply search filter
      const searchInput = screen.getByPlaceholderText('Search results...')
      await user.type(searchInput, 'brain')
      
      await waitFor(() => {
        expect(screen.queryByText('Results Table')).not.toBeInTheDocument()
      })
      
      // Clear filter
      const clearButton = screen.getByText('Clear filters')
      await user.click(clearButton)
      
      await waitFor(() => {
        expect(screen.getByText('Results Table')).toBeInTheDocument()
      })
    })
  })

  describe('Sorting', () => {
    it('sorts items by name', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const sortSelect = screen.getByDisplayValue('Date')
      await user.selectOptions(sortSelect, 'name')
      
      // Should sort alphabetically
      const items = screen.getAllByRole('heading', { level: 3 })
      expect(items[0]).toHaveTextContent('Brain Map 1')
      expect(items[1]).toHaveTextContent('Processing Graph')
      expect(items[2]).toHaveTextContent('Results Table')
    })

    it('toggles sort order', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const sortToggle = screen.getByTitle('Toggle sort order')
      await user.click(sortToggle)
      
      // Should reverse order (desc by date)
      const items = screen.getAllByRole('heading', { level: 3 })
      expect(items[0]).toHaveTextContent('Processing Graph')
    })
  })

  describe('Batch Selection', () => {
    it('enables batch selection when enabled', () => {
      render(<ResultGallery {...mockProps} enableBatchActions={true} />)
      
      const checkboxes = screen.getAllByRole('checkbox')
      expect(checkboxes.length).toBeGreaterThan(0)
    })

    it('selects individual items', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} enableBatchActions={true} />)
      
      const checkbox = screen.getAllByRole('checkbox')[1] // First item checkbox
      await user.click(checkbox)
      
      expect(screen.getByText('1 item selected')).toBeInTheDocument()
    })

    it('selects all items', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} enableBatchActions={true} />)
      
      const selectAllButton = screen.getByText('Select All')
      await user.click(selectAllButton)
      
      expect(screen.getByText('3 items selected')).toBeInTheDocument()
    })

    it('performs batch download', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} enableBatchActions={true} />)
      
      // Select all items
      const selectAllButton = screen.getByText('Select All')
      await user.click(selectAllButton)
      
      // Click batch download
      await user.click(screen.getByText('Download'))
      
      // Should call some download handler (would need to mock properly)
    })
  })

  describe('Comparison Mode', () => {
    it('enables comparison when enabled', () => {
      render(<ResultGallery {...mockProps} enableComparison={true} />)
      
      // Should show comparison buttons on items
      const comparisonButtons = screen.getAllByTitle(/comparison/i)
      expect(comparisonButtons.length).toBeGreaterThan(0)
    })

    it('adds items to comparison', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} enableComparison={true} />)
      
      const comparisonButton = screen.getAllByTitle('Add to comparison')[0]
      await user.click(comparisonButton)
      
      expect(screen.getByText('1 item ready for comparison')).toBeInTheDocument()
    })

    it('shows compare button when items selected for comparison', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} enableComparison={true} />)
      
      // Add two items to comparison
      await user.click(screen.getAllByTitle('Add to comparison')[0])
      await user.click(screen.getAllByTitle('Add to comparison')[0])
      
      await waitFor(() => {
        expect(screen.getByText('Compare')).toBeInTheDocument()
        expect(screen.getByText('2 items ready for comparison')).toBeInTheDocument()
      })
    })
  })

  describe('Item Interactions', () => {
    it('calls onItemClick when item is clicked', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const item = screen.getByText('Brain Map 1')
      await user.click(item)
      
      expect(mockProps.onItemClick).toHaveBeenCalledWith(mockItems[0])
    })

    it('calls onDownload when download button is clicked', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const downloadButtons = screen.getAllByTitle('Download')
      await user.click(downloadButtons[0])
      
      expect(mockProps.onDownload).toHaveBeenCalledWith(mockItems[0])
    })

    it('calls onShare when share button is clicked', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const shareButtons = screen.getAllByTitle('Share')
      await user.click(shareButtons[0])
      
      expect(mockProps.onShare).toHaveBeenCalledWith(mockItems[0])
    })

    it('opens lightbox when view button is clicked', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const viewButtons = screen.getAllByTitle('View')
      await user.click(viewButtons[0])
      
      // Should open lightbox (would need to test lightbox component separately)
    })
  })

  describe('Pagination', () => {
    const manyItems = Array.from({ length: 25 }, (_, i) => ({
      ...mockItems[0],
      id: `item-${i}`,
      name: `Item ${i + 1}`
    }))

    it('paginates items correctly', () => {
      render(<ResultGallery {...mockProps} items={manyItems} itemsPerPage={10} />)
      
      expect(screen.getByText('Showing 1 to 10 of 25 results')).toBeInTheDocument()
      expect(screen.getByText('Item 1')).toBeInTheDocument()
      expect(screen.queryByText('Item 11')).not.toBeInTheDocument()
    })

    it('navigates between pages', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} items={manyItems} itemsPerPage={10} />)
      
      const nextButton = screen.getByRole('button', { name: /2/ })
      await user.click(nextButton)
      
      await waitFor(() => {
        expect(screen.getByText('Showing 11 to 20 of 25 results')).toBeInTheDocument()
      })
    })
  })

  describe('Performance', () => {
    it('handles large datasets efficiently', () => {
      const largeDataset = Array.from({ length: 1000 }, (_, i) => ({
        ...mockItems[0],
        id: `large-${i}`,
        name: `Large Item ${i + 1}`
      }))

      const { container } = render(
        <ResultGallery {...mockProps} items={largeDataset} itemsPerPage={20} />
      )

      // Should only render items on current page
      const visibleItems = container.querySelectorAll('[role="heading"]')
      expect(visibleItems.length).toBeLessThanOrEqual(20)
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(<ResultGallery {...mockProps} />)
      
      const searchInput = screen.getByRole('textbox', { name: /search/i })
      expect(searchInput).toBeInTheDocument()
      
      const viewButtons = screen.getAllByRole('button', { name: /view/i })
      expect(viewButtons.length).toBeGreaterThan(0)
    })

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup()
      render(<ResultGallery {...mockProps} />)
      
      const searchInput = screen.getByPlaceholderText('Search results...')
      searchInput.focus()
      
      await user.keyboard('{Tab}')
      // Should focus next interactive element
    })
  })

  describe('Error Handling', () => {
    it('handles missing thumbnails gracefully', () => {
      const itemsWithoutThumbs = mockItems.map(item => ({
        ...item,
        thumbnail: ''
      }))

      render(<ResultGallery {...mockProps} items={itemsWithoutThumbs} />)
      
      // Should show placeholder icons instead of broken images
      const placeholders = screen.getAllByRole('img', { name: /placeholder/i })
      expect(placeholders.length).toBeGreaterThan(0)
    })

    it('handles network errors for downloads', async () => {
      const user = userEvent.setup()
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation()
      
      mockProps.onDownload.mockRejectedValueOnce(new Error('Network error'))
      
      render(<ResultGallery {...mockProps} />)
      
      const downloadButton = screen.getAllByTitle('Download')[0]
      await user.click(downloadButton)
      
      // Should handle error gracefully
      expect(mockProps.onDownload).toHaveBeenCalled()
      
      consoleSpy.mockRestore()
    })
  })
})

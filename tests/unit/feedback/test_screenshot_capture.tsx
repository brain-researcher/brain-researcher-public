/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScreenshotCapture } from '@/components/feedback/components/ScreenshotCapture'
import '@testing-library/jest-dom'

// Mock html-to-image library
const mockToPng = jest.fn()
const mockToCanvas = jest.fn()

jest.mock('html-to-image', () => ({
  toPng: mockToPng,
  toCanvas: mockToCanvas
}))

// Mock URL.createObjectURL and revokeObjectURL
global.URL.createObjectURL = jest.fn(() => 'blob:mock-url')
global.URL.revokeObjectURL = jest.fn()

// Mock File constructor
global.File = class File {
  constructor(chunks: any[], filename: string, options: any = {}) {
    this.name = filename
    this.size = chunks.reduce((acc, chunk) => acc + chunk.length, 0)
    this.type = options.type || 'application/octet-stream'
    this.lastModified = Date.now()
  }
  name: string
  size: number
  type: string
  lastModified: number
} as any

// Mock canvas context
const mockCanvas = {
  getContext: jest.fn(() => ({
    drawImage: jest.fn(),
    getImageData: jest.fn(() => ({ data: new Uint8ClampedArray(4) })),
    putImageData: jest.fn(),
    canvas: { toBlob: jest.fn() }
  })),
  toBlob: jest.fn()
}

global.HTMLCanvasElement.prototype.getContext = jest.fn(() => mockCanvas.getContext())
global.HTMLCanvasElement.prototype.toBlob = mockCanvas.toBlob

describe('ScreenshotCapture', () => {
  const mockOnScreenshotChange = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
    mockToPng.mockResolvedValue('data:image/png;base64,mockscreenshot')
    mockToCanvas.mockResolvedValue(document.createElement('canvas'))
    mockCanvas.toBlob.mockImplementation(callback => callback(new Blob(['mock'], { type: 'image/png' })))
  })

  describe('Rendering', () => {
    it('renders screenshot capture section', () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      expect(screen.getByText(/screenshot/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /capture/i })).toBeInTheDocument()
    })

    it('shows file upload option', () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      expect(screen.getByLabelText(/upload.*file/i)).toBeInTheDocument()
      expect(screen.getByText(/or upload/i)).toBeInTheDocument()
    })

    it('displays current screenshot when provided', () => {
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
      expect(screen.getByText('screenshot.png')).toBeInTheDocument()
    })

    it('shows remove option when screenshot exists', () => {
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument()
    })

    it('renders capture options when enabled', () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      expect(screen.getByRole('button', { name: /capture.*page/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /capture.*visible/i })).toBeInTheDocument()
    })
  })

  describe('File Upload', () => {
    it('handles file selection from input', async () => {
      const user = userEvent.setup()
      const mockFile = new File(['mock image data'], 'test.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, mockFile)

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(mockFile)
    })

    it('validates file type', async () => {
      const user = userEvent.setup()
      const invalidFile = new File(['mock'], 'document.pdf', { type: 'application/pdf' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, invalidFile)

      expect(screen.getByText(/please select.*image/i)).toBeInTheDocument()
      expect(mockOnScreenshotChange).not.toHaveBeenCalled()
    })

    it('validates file size', async () => {
      const user = userEvent.setup()
      // Create a large file (> 5MB)
      const largeFile = new File([new ArrayBuffer(6 * 1024 * 1024)], 'large.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, largeFile)

      expect(screen.getByText(/file.*too large/i)).toBeInTheDocument()
      expect(mockOnScreenshotChange).not.toHaveBeenCalled()
    })

    it('handles multiple file selection (uses first file)', async () => {
      const user = userEvent.setup()
      const file1 = new File(['mock1'], 'test1.png', { type: 'image/png' })
      const file2 = new File(['mock2'], 'test2.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, [file1, file2])

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(file1)
    })
  })

  describe('Screenshot Capture', () => {
    it('captures full page screenshot', async () => {
      const user = userEvent.setup()

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*page/i })
      await user.click(captureButton)

      await waitFor(() => {
        expect(mockToPng).toHaveBeenCalledWith(document.body, expect.any(Object))
      })

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(expect.any(File))
    })

    it('captures visible area screenshot', async () => {
      const user = userEvent.setup()

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*visible/i })
      await user.click(captureButton)

      await waitFor(() => {
        expect(mockToPng).toHaveBeenCalledWith(document.body, expect.objectContaining({
          width: window.innerWidth,
          height: window.innerHeight
        }))
      })

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(expect.any(File))
    })

    it('shows loading state during capture', async () => {
      const user = userEvent.setup()
      let resolveToPng: (value: string) => void
      mockToPng.mockImplementation(() => new Promise(resolve => {
        resolveToPng = resolve
      }))

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*page/i })
      await user.click(captureButton)

      expect(screen.getByText(/capturing/i)).toBeInTheDocument()
      expect(captureButton).toBeDisabled()

      // Resolve the capture
      act(() => {
        resolveToPng!('data:image/png;base64,captured')
      })

      await waitFor(() => {
        expect(screen.queryByText(/capturing/i)).not.toBeInTheDocument()
      })
    })

    it('handles capture errors', async () => {
      const user = userEvent.setup()
      const captureError = new Error('Capture failed')
      mockToPng.mockRejectedValue(captureError)

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*page/i })
      await user.click(captureButton)

      await waitFor(() => {
        expect(screen.getByText(/failed.*capture/i)).toBeInTheDocument()
      })

      expect(mockOnScreenshotChange).not.toHaveBeenCalled()
    })

    it('uses custom capture options', async () => {
      const user = userEvent.setup()
      const customOptions = {
        quality: 0.8,
        excludeSelectors: ['.sensitive-data'],
        maskSensitiveData: true
      }

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
          captureOptions={customOptions}
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*page/i })
      await user.click(captureButton)

      await waitFor(() => {
        expect(mockToPng).toHaveBeenCalledWith(document.body, expect.objectContaining({
          quality: 0.8
        }))
      })
    })
  })

  describe('Drag and Drop', () => {
    it('handles file drop', async () => {
      const mockFile = new File(['mock'], 'dropped.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const dropzone = screen.getByTestId('screenshot-dropzone')
      
      await act(async () => {
        fireEvent.drop(dropzone, {
          dataTransfer: {
            files: [mockFile]
          }
        })
      })

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(mockFile)
    })

    it('shows drag over state', async () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const dropzone = screen.getByTestId('screenshot-dropzone')
      
      fireEvent.dragOver(dropzone)
      expect(dropzone).toHaveClass('drag-over')

      fireEvent.dragLeave(dropzone)
      expect(dropzone).not.toHaveClass('drag-over')
    })

    it('validates dropped files', async () => {
      const invalidFile = new File(['mock'], 'document.txt', { type: 'text/plain' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const dropzone = screen.getByTestId('screenshot-dropzone')
      
      await act(async () => {
        fireEvent.drop(dropzone, {
          dataTransfer: {
            files: [invalidFile]
          }
        })
      })

      expect(screen.getByText(/please select.*image/i)).toBeInTheDocument()
      expect(mockOnScreenshotChange).not.toHaveBeenCalled()
    })
  })

  describe('Screenshot Management', () => {
    it('removes screenshot when remove button is clicked', async () => {
      const user = userEvent.setup()
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const removeButton = screen.getByRole('button', { name: /remove/i })
      await user.click(removeButton)

      expect(mockOnScreenshotChange).toHaveBeenCalledWith(null)
    })

    it('shows screenshot preview with details', () => {
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })
      Object.defineProperty(mockFile, 'size', { value: 1024 * 50 }) // 50KB

      render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      expect(screen.getByText('screenshot.png')).toBeInTheDocument()
      expect(screen.getByText(/50.*KB/i)).toBeInTheDocument()
    })

    it('displays screenshot thumbnail', () => {
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const thumbnail = screen.getByRole('img', { name: /screenshot.*preview/i })
      expect(thumbnail).toBeInTheDocument()
      expect(thumbnail).toHaveAttribute('src', 'blob:mock-url')
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      expect(screen.getByRole('button', { name: /capture.*page/i })).toHaveAttribute('aria-label')
      expect(screen.getByRole('button', { name: /capture.*visible/i })).toHaveAttribute('aria-label')
    })

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup()

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      // Tab to file input
      await user.tab()
      expect(screen.getByLabelText(/upload.*file/i)).toHaveFocus()

      // Tab to capture buttons
      await user.tab()
      expect(screen.getByRole('button', { name: /capture.*page/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /capture.*visible/i })).toHaveFocus()
    })

    it('has proper focus management', async () => {
      const user = userEvent.setup()
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      const { rerender } = render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      // Add screenshot
      rerender(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      // Remove button should be focusable
      await user.tab()
      expect(screen.getByRole('button', { name: /remove/i })).toHaveFocus()
    })

    it('announces screenshot changes to screen readers', async () => {
      const user = userEvent.setup()
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, mockFile)

      expect(screen.getByRole('status')).toHaveTextContent(/screenshot.*added/i)
    })

    it('has proper error announcements', async () => {
      const user = userEvent.setup()
      const invalidFile = new File(['mock'], 'document.pdf', { type: 'application/pdf' })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      const fileInput = screen.getByLabelText(/upload.*file/i)
      await user.upload(fileInput, invalidFile)

      expect(screen.getByRole('alert')).toHaveTextContent(/please select.*image/i)
    })
  })

  describe('Edge Cases', () => {
    it('handles disabled state', () => {
      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          disabled
        />
      )

      expect(screen.getByLabelText(/upload.*file/i)).toBeDisabled()
    })

    it('handles missing onScreenshotChange callback', () => {
      expect(() => {
        render(
          <ScreenshotCapture
            screenshot={null}
            onScreenshotChange={undefined as any}
          />
        )
      }).not.toThrow()
    })

    it('handles capture when html-to-image is not available', async () => {
      const user = userEvent.setup()
      mockToPng.mockImplementation(() => {
        throw new Error('html-to-image not available')
      })

      render(
        <ScreenshotCapture
          screenshot={null}
          onScreenshotChange={mockOnScreenshotChange}
          enableCapture
        />
      )

      const captureButton = screen.getByRole('button', { name: /capture.*page/i })
      await user.click(captureButton)

      await waitFor(() => {
        expect(screen.getByText(/screenshot.*not.*supported/i)).toBeInTheDocument()
      })
    })

    it('cleans up object URLs on unmount', () => {
      const mockFile = new File(['mock'], 'screenshot.png', { type: 'image/png' })

      const { unmount } = render(
        <ScreenshotCapture
          screenshot={mockFile}
          onScreenshotChange={mockOnScreenshotChange}
        />
      )

      unmount()

      expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    })
  })
})
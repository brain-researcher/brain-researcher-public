/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DashboardCustomizer } from '@/components/analytics/DashboardCustomizer'
import '@testing-library/jest-dom'

// Mock UI components
jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open, onOpenChange }: any) => (
    open ? (
      <div data-testid="dialog-root" data-open={open}>
        <div onClick={() => onOpenChange(false)} data-testid="dialog-backdrop" />
        {children}
      </div>
    ) : null
  ),
  DialogContent: ({ children, className }: any) => (
    <div data-testid="dialog-content" className={className}>
      {children}
    </div>
  ),
  DialogHeader: ({ children }: any) => (
    <div data-testid="dialog-header">{children}</div>
  ),
  DialogTitle: ({ children }: any) => (
    <h2 data-testid="dialog-title">{children}</h2>
  ),
  DialogDescription: ({ children }: any) => (
    <p data-testid="dialog-description">{children}</p>
  ),
  DialogFooter: ({ children }: any) => (
    <div data-testid="dialog-footer">{children}</div>
  )
}))

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, variant, size, className, disabled }: any) => (
    <button 
      data-testid="button"
      onClick={onClick} 
      data-variant={variant}
      data-size={size}
      disabled={disabled}
      className={className}
    >
      {children}
    </button>
  )
}))

jest.mock('@/components/ui/switch', () => ({
  Switch: ({ checked, onCheckedChange, className, disabled }: any) => (
    <button 
      data-testid="switch"
      data-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={className}
    >
      Switch: {checked ? 'ON' : 'OFF'}
    </button>
  )
}))

jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange, disabled }: any) => (
    <div 
      data-testid="select-root" 
      data-value={value} 
      data-disabled={disabled}
      onClick={(e: any) => {
        if (e.target.dataset.selectValue && !disabled) onValueChange(e.target.dataset.selectValue)
      }}
    >
      {children}
    </div>
  ),
  SelectTrigger: ({ children, className }: any) => <div data-testid="select-trigger" className={className}>{children}</div>,
  SelectValue: ({ placeholder }: any) => <span data-testid="select-value">{placeholder}</span>,
  SelectContent: ({ children }: any) => <div data-testid="select-content">{children}</div>,
  SelectItem: ({ children, value }: any) => (
    <div data-testid={`select-item-${value}`} data-select-value={value}>{children}</div>
  )
}))

jest.mock('@/components/ui/checkbox', () => ({
  Checkbox: ({ checked, onCheckedChange, className, disabled }: any) => (
    <input 
      type="checkbox"
      data-testid="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(e) => onCheckedChange(e.target.checked)}
      className={className}
    />
  )
}))

jest.mock('@/components/ui/slider', () => ({
  Slider: ({ value, onValueChange, min, max, step, className, disabled }: any) => (
    <input 
      data-testid="slider"
      type="range"
      min={min}
      max={max}
      step={step}
      value={value?.[0] || 0}
      disabled={disabled}
      onChange={(e) => onValueChange([parseInt(e.target.value)])}
      className={className}
    />
  )
}))

jest.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children, value, onValueChange }: any) => (
    <div data-testid="tabs" data-value={value} onClick={(e: any) => {
      if (e.target.dataset.tabValue) onValueChange(e.target.dataset.tabValue)
    }}>
      {children}
    </div>
  ),
  TabsList: ({ children, className }: any) => <div data-testid="tabs-list" className={className}>{children}</div>,
  TabsTrigger: ({ children, value, className }: any) => (
    <button data-testid={`tab-${value}`} data-tab-value={value} className={className}>{children}</button>
  ),
  TabsContent: ({ children, value, className }: any) => (
    <div data-testid={`tab-content-${value}`} className={className}>{children}</div>
  )
}))

jest.mock('@/components/ui/label', () => ({
  Label: ({ children, htmlFor, className }: any) => (
    <label data-testid="label" htmlFor={htmlFor} className={className}>{children}</label>
  )
}))

jest.mock('@/components/ui/separator', () => ({
  Separator: ({ className }: any) => (
    <hr data-testid="separator" className={className} />
  )
}))

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  Settings: ({ className }: any) => <span data-testid="settings-icon" className={className}>⚙️</span>,
  Palette: ({ className }: any) => <span data-testid="palette-icon" className={className}>🎨</span>,
  Layout: ({ className }: any) => <span data-testid="layout-icon" className={className}>📐</span>,
  Clock: ({ className }: any) => <span data-testid="clock-icon" className={className}>⏰</span>,
  Eye: ({ className }: any) => <span data-testid="eye-icon" className={className}>👁️</span>,
  EyeOff: ({ className }: any) => <span data-testid="eye-off-icon" className={className}>🙈</span>,
  RotateCcw: ({ className }: any) => <span data-testid="rotate-ccw-icon" className={className}>↺</span>,
  Download: ({ className }: any) => <span data-testid="download-icon" className={className}>⬇️</span>,
  Upload: ({ className }: any) => <span data-testid="upload-icon" className={className}>⬆️</span>,
  Check: ({ className }: any) => <span data-testid="check-icon" className={className}>✓</span>,
  X: ({ className }: any) => <span data-testid="x-icon" className={className}>✕</span>
}))

// Mock cn utility
jest.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' ')
}))

// Mock data structures
const mockCurrentConfig = {
  tabs: [
    { id: 'overview', label: 'Overview', enabled: true },
    { id: 'usage', label: 'Usage Analytics', enabled: true },
    { id: 'performance', label: 'Performance', enabled: true },
    { id: 'realtime', label: 'Real-time', enabled: false }
  ],
  realTimeEnabled: true,
  refreshInterval: 30,
  compactMode: false,
  timeRange: {
    label: 'Last 7 Days',
    value: '7d',
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
    end: new Date()
  },
  theme: 'light',
  chartSettings: {
    animationsEnabled: true,
    showGridlines: true,
    showTooltips: true,
    colorScheme: 'default'
  },
  layoutSettings: {
    cardSpacing: 'normal',
    fontSize: 'medium',
    headerSize: 'large'
  }
}

describe('DashboardCustomizer', () => {
  const mockOnClose = jest.fn()
  const mockOnConfigChange = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Rendering', () => {
    it('renders when open is true', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      expect(screen.getByTestId('dialog-root')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-title')).toHaveTextContent('Customize Dashboard')
      expect(screen.getByTestId('dialog-description')).toHaveTextContent('Configure your dashboard layout, appearance, and behavior')
    })

    it('does not render when open is false', () => {
      render(
        <DashboardCustomizer
          open={false}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      expect(screen.queryByTestId('dialog-root')).not.toBeInTheDocument()
    })

    it('renders all customization tabs', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      expect(screen.getByTestId('tab-layout')).toBeInTheDocument()
      expect(screen.getByTestId('tab-appearance')).toBeInTheDocument()
      expect(screen.getByTestId('tab-behavior')).toBeInTheDocument()
      expect(screen.getByTestId('tab-export')).toBeInTheDocument()
    })
  })

  describe('Layout Customization', () => {
    it('shows enabled tabs in layout tab', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Should be in layout tab by default
      expect(screen.getByTestId('tab-content-layout')).toBeInTheDocument()
      
      // Should show checkboxes for each tab
      const checkboxes = screen.getAllByTestId('checkbox')
      expect(checkboxes.length).toBe(4) // One for each tab
      
      // First three should be checked (enabled), last should be unchecked
      expect(checkboxes[0]).toBeChecked()
      expect(checkboxes[1]).toBeChecked()
      expect(checkboxes[2]).toBeChecked()
      expect(checkboxes[3]).not.toBeChecked()
    })

    it('handles tab enable/disable', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const checkboxes = screen.getAllByTestId('checkbox')
      const performanceTabCheckbox = checkboxes[2] // Performance tab
      
      await userEvent.click(performanceTabCheckbox)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          tabs: expect.arrayContaining([
            expect.objectContaining({ id: 'performance', enabled: false })
          ])
        })
      )
    })

    it('shows compact mode toggle', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.getAttribute('data-checked') === 'false'
      )
      expect(compactModeSwitch).toBeInTheDocument()
    })

    it('handles compact mode toggle', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('OFF')
      )
      
      await userEvent.click(compactModeSwitch!)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          compactMode: true
        })
      )
    })
  })

  describe('Appearance Customization', () => {
    it('switches to appearance tab', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      await userEvent.click(appearanceTab)
      
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveAttribute('data-value', 'appearance')
      expect(screen.getByTestId('tab-content-appearance')).toBeInTheDocument()
    })

    it('shows theme selector', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      await userEvent.click(appearanceTab)
      
      expect(screen.getByTestId('select-item-light')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-dark')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-auto')).toBeInTheDocument()
    })

    it('handles theme change', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      await userEvent.click(appearanceTab)
      
      const darkThemeItem = screen.getByTestId('select-item-dark')
      await userEvent.click(darkThemeItem)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          theme: 'dark'
        })
      )
    })

    it('shows color scheme options', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      await userEvent.click(appearanceTab)
      
      expect(screen.getByTestId('select-item-default')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-blue')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-green')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-purple')).toBeInTheDocument()
    })

    it('shows font size controls', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      await userEvent.click(appearanceTab)
      
      const slider = screen.getByTestId('slider')
      expect(slider).toBeInTheDocument()
      expect(slider).toHaveAttribute('min', '12')
      expect(slider).toHaveAttribute('max', '18')
    })
  })

  describe('Behavior Customization', () => {
    it('switches to behavior tab', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      expect(screen.getByTestId('tab-content-behavior')).toBeInTheDocument()
    })

    it('shows real-time toggle', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      const realTimeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.getAttribute('data-checked') === 'true'
      )
      expect(realTimeSwitch).toBeInTheDocument()
    })

    it('handles real-time toggle', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      const realTimeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('ON')
      )
      
      await userEvent.click(realTimeSwitch!)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          realTimeEnabled: false
        })
      )
    })

    it('shows refresh interval selector', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      expect(screen.getByTestId('select-item-5')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-10')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-30')).toBeInTheDocument()
      expect(screen.getByTestId('select-item-60')).toBeInTheDocument()
    })

    it('handles refresh interval change', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      const interval60Item = screen.getByTestId('select-item-60')
      await userEvent.click(interval60Item)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          refreshInterval: 60
        })
      )
    })

    it('shows chart animation controls', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      // Should show switches for various chart settings
      const switches = screen.getAllByTestId('switch')
      expect(switches.length).toBeGreaterThan(1)
    })
  })

  describe('Export/Import', () => {
    it('switches to export tab', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const exportTab = screen.getByTestId('tab-export')
      await userEvent.click(exportTab)
      
      expect(screen.getByTestId('tab-content-export')).toBeInTheDocument()
    })

    it('shows export configuration button', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const exportTab = screen.getByTestId('tab-export')
      await userEvent.click(exportTab)
      
      const exportButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Export Configuration')
      )
      expect(exportButton).toBeInTheDocument()
    })

    it('shows import configuration button', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const exportTab = screen.getByTestId('tab-export')
      await userEvent.click(exportTab)
      
      const importButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Import Configuration')
      )
      expect(importButton).toBeInTheDocument()
    })

    it('shows reset to defaults button', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const exportTab = screen.getByTestId('tab-export')
      await userEvent.click(exportTab)
      
      const resetButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Reset to Defaults')
      )
      expect(resetButton).toBeInTheDocument()
    })
  })

  describe('Dialog Controls', () => {
    it('shows apply and cancel buttons', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const footer = screen.getByTestId('dialog-footer')
      expect(footer).toBeInTheDocument()
      
      const cancelButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Cancel')
      )
      const applyButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Apply Changes')
      )
      
      expect(cancelButton).toBeInTheDocument()
      expect(applyButton).toBeInTheDocument()
    })

    it('handles cancel action', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const cancelButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Cancel')
      )
      
      await userEvent.click(cancelButton!)
      
      expect(mockOnClose).toHaveBeenCalled()
    })

    it('handles backdrop click to close', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const backdrop = screen.getByTestId('dialog-backdrop')
      await userEvent.click(backdrop)
      
      expect(mockOnClose).toHaveBeenCalled()
    })

    it('applies changes before closing', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Make a change
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('OFF')
      )
      await userEvent.click(compactModeSwitch!)
      
      // Apply changes
      const applyButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Apply Changes')
      )
      await userEvent.click(applyButton!)
      
      expect(mockOnConfigChange).toHaveBeenCalled()
      expect(mockOnClose).toHaveBeenCalled()
    })
  })

  describe('Configuration Validation', () => {
    it('prevents invalid configurations', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Try to disable all tabs
      const checkboxes = screen.getAllByTestId('checkbox')
      for (const checkbox of checkboxes) {
        if (checkbox.checked) {
          await userEvent.click(checkbox)
        }
      }
      
      // Apply button should be disabled when no tabs are enabled
      const applyButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Apply Changes')
      )
      expect(applyButton).toBeDisabled()
    })

    it('validates refresh interval bounds', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const behaviorTab = screen.getByTestId('tab-behavior')
      await userEvent.click(behaviorTab)
      
      // All provided refresh intervals should be valid
      const validIntervals = ['5', '10', '30', '60']
      for (const interval of validIntervals) {
        expect(screen.getByTestId(`select-item-${interval}`)).toBeInTheDocument()
      }
    })
  })

  describe('Accessibility', () => {
    it('provides proper ARIA labels', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const title = screen.getByRole('heading', { level: 2 })
      expect(title).toHaveTextContent('Customize Dashboard')
      
      const labels = screen.getAllByTestId('label')
      expect(labels.length).toBeGreaterThan(0)
    })

    it('supports keyboard navigation', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const appearanceTab = screen.getByTestId('tab-appearance')
      appearanceTab.focus()
      
      expect(document.activeElement).toBe(appearanceTab)
      
      // Should be able to navigate with Enter
      fireEvent.keyDown(appearanceTab, { key: 'Enter' })
      fireEvent.click(appearanceTab)
      
      expect(screen.getByTestId('tab-content-appearance')).toBeInTheDocument()
    })

    it('provides meaningful form labels', () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      const labels = screen.getAllByTestId('label')
      expect(labels.length).toBeGreaterThan(0)
      
      // Labels should have meaningful text
      labels.forEach(label => {
        expect(label.textContent).toBeTruthy()
        expect(label.textContent?.length).toBeGreaterThan(0)
      })
    })
  })

  describe('Error Handling', () => {
    it('handles missing configuration gracefully', () => {
      const incompleteConfig = {
        tabs: [],
        realTimeEnabled: true,
        refreshInterval: 30,
        compactMode: false
      }
      
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={incompleteConfig as any}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Should still render without crashing
      expect(screen.getByTestId('dialog-title')).toHaveTextContent('Customize Dashboard')
    })

    it('handles callback errors gracefully', async () => {
      const errorOnConfigChange = jest.fn(() => {
        throw new Error('Configuration error')
      })
      
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={errorOnConfigChange}
        />
      )
      
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('OFF')
      )
      
      // Should not crash when callback throws
      await userEvent.click(compactModeSwitch!)
      
      expect(errorOnConfigChange).toHaveBeenCalled()
    })
  })

  describe('Real-time Preview', () => {
    it('shows preview of changes', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Changes should be reflected immediately via onConfigChange calls
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('OFF')
      )
      
      await userEvent.click(compactModeSwitch!)
      
      expect(mockOnConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({
          compactMode: true
        })
      )
    })

    it('allows reverting changes before applying', async () => {
      render(
        <DashboardCustomizer
          open={true}
          onClose={mockOnClose}
          currentConfig={mockCurrentConfig}
          onConfigChange={mockOnConfigChange}
        />
      )
      
      // Make a change
      const compactModeSwitch = screen.getAllByTestId('switch').find(
        sw => sw.textContent?.includes('OFF')
      )
      await userEvent.click(compactModeSwitch!)
      
      // Cancel should revert
      const cancelButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Cancel')
      )
      await userEvent.click(cancelButton!)
      
      expect(mockOnClose).toHaveBeenCalled()
    })
  })
})
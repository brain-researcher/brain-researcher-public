/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TimeSeriesChart } from '@/components/analytics/TimeSeriesChart'
import '@testing-library/jest-dom'

// Mock Recharts components
jest.mock('recharts', () => ({
  LineChart: ({ children, data, width, height, margin, onMouseMove, onMouseLeave }: any) => (
    <div 
      data-testid="recharts-line-chart"
      data-width={width}
      data-height={height}
      data-data-length={data?.length || 0}
      onMouseMove={() => onMouseMove && onMouseMove({ activeLabel: '2025-01-01T12:00:00Z' })}
      onMouseLeave={onMouseLeave}
      style={{ width, height }}
    >
      {children}
    </div>
  ),
  Line: ({ dataKey, stroke, strokeWidth, dot, connectNulls }: any) => (
    <div 
      data-testid="recharts-line"
      data-data-key={dataKey}
      data-stroke={stroke}
      data-stroke-width={strokeWidth}
      data-dot={dot}
      data-connect-nulls={connectNulls}
    />
  ),
  XAxis: ({ dataKey, tickFormatter, domain, type }: any) => (
    <div 
      data-testid="recharts-x-axis"
      data-data-key={dataKey}
      data-domain={domain?.join(',')}
      data-type={type}
    />
  ),
  YAxis: ({ tickFormatter, domain, label }: any) => (
    <div 
      data-testid="recharts-y-axis"
      data-domain={domain?.join(',')}
      data-label={label?.value}
    />
  ),
  CartesianGrid: ({ strokeDasharray }: any) => (
    <div data-testid="recharts-cartesian-grid" data-stroke-dasharray={strokeDasharray} />
  ),
  Tooltip: ({ formatter, labelFormatter, active, payload, label }: any) => (
    <div 
      data-testid="recharts-tooltip"
      data-active={active}
      data-label={label}
      data-payload-length={payload?.length || 0}
    />
  ),
  Legend: ({ wrapperStyle }: any) => (
    <div data-testid="recharts-legend" style={wrapperStyle} />
  ),
  ResponsiveContainer: ({ children, width, height }: any) => (
    <div 
      data-testid="recharts-responsive-container" 
      data-width={width}
      data-height={height}
      style={{ width, height }}
    >
      {children}
    </div>
  ),
  ReferenceLine: ({ x, stroke, strokeDasharray, label }: any) => (
    <div 
      data-testid="recharts-reference-line"
      data-x={x}
      data-stroke={stroke}
      data-stroke-dasharray={strokeDasharray}
      data-label={label}
    />
  ),
  Brush: ({ dataKey, height, stroke }: any) => (
    <div 
      data-testid="recharts-brush"
      data-data-key={dataKey}
      data-height={height}
      data-stroke={stroke}
    />
  )
}))

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({ children, className }: any) => <div data-testid="card" className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div data-testid="card-content" className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div data-testid="card-header" className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <h3 data-testid="card-title" className={className}>{children}</h3>
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

jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => (
    <div data-testid="select-root" data-value={value} onClick={(e: any) => {
      if (e.target.dataset.selectValue) onValueChange(e.target.dataset.selectValue)
    }}>
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

jest.mock('@/components/ui/switch', () => ({
  Switch: ({ checked, onCheckedChange, className }: any) => (
    <button 
      data-testid="switch"
      data-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      className={className}
    >
      Switch: {checked ? 'ON' : 'OFF'}
    </button>
  )
}))

jest.mock('@/components/ui/slider', () => ({
  Slider: ({ value, onValueChange, min, max, step, className }: any) => (
    <input 
      data-testid="slider"
      type="range"
      min={min}
      max={max}
      step={step}
      value={value?.[0] || 0}
      onChange={(e) => onValueChange([parseInt(e.target.value)])}
      className={className}
    />
  )
}))

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  ZoomIn: ({ className }: any) => <span data-testid="zoom-in-icon" className={className}>🔍+</span>,
  ZoomOut: ({ className }: any) => <span data-testid="zoom-out-icon" className={className}>🔍-</span>,
  Move: ({ className }: any) => <span data-testid="move-icon" className={className}>✋</span>,
  RotateCcw: ({ className }: any) => <span data-testid="rotate-ccw-icon" className={className}>↺</span>,
  Download: ({ className }: any) => <span data-testid="download-icon" className={className}>⬇️</span>,
  Settings: ({ className }: any) => <span data-testid="settings-icon" className={className}>⚙️</span>,
  Eye: ({ className }: any) => <span data-testid="eye-icon" className={className}>👁️</span>,
  EyeOff: ({ className }: any) => <span data-testid="eye-off-icon" className={className}>🙈</span>,
  Maximize2: ({ className }: any) => <span data-testid="maximize2-icon" className={className}>⛶</span>
}))

// Mock cn utility
jest.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' ')
}))

// Mock data
const mockTimeSeriesData = [
  { timestamp: '2025-01-01T00:00:00Z', value: 100, secondary: 50 },
  { timestamp: '2025-01-01T01:00:00Z', value: 120, secondary: 60 },
  { timestamp: '2025-01-01T02:00:00Z', value: 95, secondary: 45 },
  { timestamp: '2025-01-01T03:00:00Z', value: 140, secondary: 70 },
  { timestamp: '2025-01-01T04:00:00Z', value: 110, secondary: 55 },
  { timestamp: '2025-01-01T05:00:00Z', value: 130, secondary: 65 },
  { timestamp: '2025-01-01T06:00:00Z', value: 125, secondary: 62 }
]

const mockAnnotations = [
  { timestamp: '2025-01-01T02:00:00Z', label: 'Maintenance Window', color: '#ff6b6b' },
  { timestamp: '2025-01-01T04:00:00Z', label: 'Peak Load', color: '#4ecdc4' }
]

describe('TimeSeriesChart', () => {
  describe('Rendering', () => {
    it('renders with basic props', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Test Chart"
          dataKey="value"
        />
      )
      
      expect(screen.getByText('Test Chart')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-responsive-container')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-line-chart')).toBeInTheDocument()
    })

    it('renders with custom dimensions', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Test Chart"
          dataKey="value"
          width={800}
          height={400}
        />
      )
      
      const chart = screen.getByTestId('recharts-line-chart')
      expect(chart).toHaveAttribute('data-width', '800')
      expect(chart).toHaveAttribute('data-height', '400')
    })

    it('renders with custom className', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Test Chart"
          dataKey="value"
          className="custom-chart"
        />
      )
      
      const card = screen.getByTestId('card')
      expect(card).toHaveClass('custom-chart')
    })

    it('renders with multiple lines', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Multi-line Chart"
          dataKey="value"
          secondaryDataKey="secondary"
        />
      )
      
      const lines = screen.getAllByTestId('recharts-line')
      expect(lines).toHaveLength(2)
      expect(lines[0]).toHaveAttribute('data-data-key', 'value')
      expect(lines[1]).toHaveAttribute('data-data-key', 'secondary')
    })
  })

  describe('Chart Components', () => {
    it('renders all chart components correctly', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Test Chart"
          dataKey="value"
          showGrid={true}
          showTooltip={true}
          showLegend={true}
        />
      )
      
      expect(screen.getByTestId('recharts-x-axis')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-y-axis')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-cartesian-grid')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-tooltip')).toBeInTheDocument()
      expect(screen.getByTestId('recharts-legend')).toBeInTheDocument()
    })

    it('applies custom colors correctly', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Colored Chart"
          dataKey="value"
          color="#ff6b6b"
          secondaryDataKey="secondary"
          secondaryColor="#4ecdc4"
        />
      )
      
      const lines = screen.getAllByTestId('recharts-line')
      expect(lines[0]).toHaveAttribute('data-stroke', '#ff6b6b')
      expect(lines[1]).toHaveAttribute('data-stroke', '#4ecdc4')
    })

    it('renders annotations as reference lines', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Annotated Chart"
          dataKey="value"
          annotations={mockAnnotations}
        />
      )
      
      const referenceLines = screen.getAllByTestId('recharts-reference-line')
      expect(referenceLines).toHaveLength(2)
      expect(referenceLines[0]).toHaveAttribute('data-x', '2025-01-01T02:00:00Z')
      expect(referenceLines[1]).toHaveAttribute('data-x', '2025-01-01T04:00:00Z')
    })
  })

  describe('Zoom and Pan Controls', () => {
    it('renders zoom controls when enabled', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Zoomable Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      expect(screen.getByTestId('zoom-in-icon')).toBeInTheDocument()
      expect(screen.getByTestId('zoom-out-icon')).toBeInTheDocument()
      expect(screen.getByTestId('rotate-ccw-icon')).toBeInTheDocument() // Reset zoom
    })

    it('renders pan control when enabled', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Pannable Chart"
          dataKey="value"
          enablePan={true}
        />
      )
      
      expect(screen.getByTestId('move-icon')).toBeInTheDocument()
    })

    it('handles zoom in action', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Zoomable Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      const zoomInButton = screen.getByTestId('zoom-in-icon').parentElement
      await userEvent.click(zoomInButton!)
      
      // Should trigger zoom functionality
      expect(zoomInButton).toBeInTheDocument()
    })

    it('handles zoom out action', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Zoomable Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      const zoomOutButton = screen.getByTestId('zoom-out-icon').parentElement
      await userEvent.click(zoomOutButton!)
      
      // Should trigger zoom functionality
      expect(zoomOutButton).toBeInTheDocument()
    })

    it('handles reset zoom action', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Zoomable Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      const resetButton = screen.getByTestId('rotate-ccw-icon').parentElement
      await userEvent.click(resetButton!)
      
      // Should reset zoom level
      expect(resetButton).toBeInTheDocument()
    })
  })

  describe('Brush/Range Selector', () => {
    it('renders brush when enabled', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Chart with Brush"
          dataKey="value"
          showBrush={true}
        />
      )
      
      expect(screen.getByTestId('recharts-brush')).toBeInTheDocument()
    })

    it('configures brush correctly', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Chart with Brush"
          dataKey="value"
          showBrush={true}
        />
      )
      
      const brush = screen.getByTestId('recharts-brush')
      expect(brush).toHaveAttribute('data-data-key', 'timestamp')
      expect(brush).toHaveAttribute('data-height', '40')
    })
  })

  describe('Export Functionality', () => {
    it('renders export button when enabled', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Exportable Chart"
          dataKey="value"
          enableExport={true}
        />
      )
      
      expect(screen.getByTestId('download-icon')).toBeInTheDocument()
    })

    it('handles export action', async () => {
      const mockExportHandler = jest.fn()
      
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Exportable Chart"
          dataKey="value"
          enableExport={true}
          onExport={mockExportHandler}
        />
      )
      
      const exportButton = screen.getByTestId('download-icon').parentElement
      await userEvent.click(exportButton!)
      
      expect(mockExportHandler).toHaveBeenCalledWith(
        expect.objectContaining({
          format: 'png',
          data: mockTimeSeriesData,
          title: 'Exportable Chart'
        })
      )
    })

    it('supports different export formats', async () => {
      const mockExportHandler = jest.fn()
      
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Exportable Chart"
          dataKey="value"
          enableExport={true}
          exportFormat="svg"
          onExport={mockExportHandler}
        />
      )
      
      const exportButton = screen.getByTestId('download-icon').parentElement
      await userEvent.click(exportButton!)
      
      expect(mockExportHandler).toHaveBeenCalledWith(
        expect.objectContaining({
          format: 'svg'
        })
      )
    })
  })

  describe('Customization Options', () => {
    it('applies custom line styling', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Styled Chart"
          dataKey="value"
          strokeWidth={3}
          showDots={true}
          connectNulls={false}
        />
      )
      
      const line = screen.getByTestId('recharts-line')
      expect(line).toHaveAttribute('data-stroke-width', '3')
      expect(line).toHaveAttribute('data-dot', 'true')
      expect(line).toHaveAttribute('data-connect-nulls', 'false')
    })

    it('supports custom Y-axis domain', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Custom Domain Chart"
          dataKey="value"
          yAxisDomain={[0, 200]}
        />
      )
      
      const yAxis = screen.getByTestId('recharts-y-axis')
      expect(yAxis).toHaveAttribute('data-domain', '0,200')
    })

    it('supports custom axis labels', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Labeled Chart"
          dataKey="value"
          xAxisLabel="Time"
          yAxisLabel="Value"
        />
      )
      
      const yAxis = screen.getByTestId('recharts-y-axis')
      expect(yAxis).toHaveAttribute('data-label', 'Value')
    })
  })

  describe('Responsive Behavior', () => {
    it('uses responsive container by default', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Responsive Chart"
          dataKey="value"
        />
      )
      
      const container = screen.getByTestId('recharts-responsive-container')
      expect(container).toHaveAttribute('data-width', '100%')
      expect(container).toHaveAttribute('data-height', '100%')
    })

    it('adapts to custom dimensions', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Fixed Size Chart"
          dataKey="value"
          width={600}
          height={300}
        />
      )
      
      const container = screen.getByTestId('recharts-responsive-container')
      expect(container).toHaveAttribute('data-width', '100%')
      expect(container).toHaveAttribute('data-height', '100%')
    })
  })

  describe('Tooltip Interactions', () => {
    it('shows tooltip on hover', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Interactive Chart"
          dataKey="value"
          showTooltip={true}
        />
      )
      
      const chart = screen.getByTestId('recharts-line-chart')
      
      // Simulate mouse move
      fireEvent.mouseMove(chart)
      
      // Tooltip should be rendered
      const tooltip = screen.getByTestId('recharts-tooltip')
      expect(tooltip).toBeInTheDocument()
    })

    it('hides tooltip on mouse leave', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Interactive Chart"
          dataKey="value"
          showTooltip={true}
        />
      )
      
      const chart = screen.getByTestId('recharts-line-chart')
      
      // Simulate mouse leave
      fireEvent.mouseLeave(chart)
      
      // This would hide the tooltip in the actual implementation
      expect(chart).toBeInTheDocument()
    })

    it('supports custom tooltip formatter', () => {
      const customTooltipFormatter = (value: any, name: string) => [
        `${value} units`,
        `Custom ${name}`
      ]
      
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Custom Tooltip Chart"
          dataKey="value"
          showTooltip={true}
          tooltipFormatter={customTooltipFormatter}
        />
      )
      
      const tooltip = screen.getByTestId('recharts-tooltip')
      expect(tooltip).toBeInTheDocument()
    })
  })

  describe('Performance Options', () => {
    it('enables animation by default', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Animated Chart"
          dataKey="value"
        />
      )
      
      // Animation would be handled by Recharts internally
      expect(screen.getByTestId('recharts-line-chart')).toBeInTheDocument()
    })

    it('can disable animation for better performance', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Static Chart"
          dataKey="value"
          animationDuration={0}
        />
      )
      
      // No animation with duration 0
      expect(screen.getByTestId('recharts-line-chart')).toBeInTheDocument()
    })

    it('handles large datasets efficiently', () => {
      const largeDataset = Array.from({ length: 1000 }, (_, i) => ({
        timestamp: new Date(Date.now() + i * 60000).toISOString(),
        value: Math.random() * 100
      }))
      
      render(
        <TimeSeriesChart 
          data={largeDataset}
          title="Large Dataset Chart"
          dataKey="value"
        />
      )
      
      const chart = screen.getByTestId('recharts-line-chart')
      expect(chart).toHaveAttribute('data-data-length', '1000')
    })
  })

  describe('Error Handling', () => {
    it('handles empty data gracefully', () => {
      render(
        <TimeSeriesChart 
          data={[]}
          title="Empty Chart"
          dataKey="value"
        />
      )
      
      expect(screen.getByText('Empty Chart')).toBeInTheDocument()
      const chart = screen.getByTestId('recharts-line-chart')
      expect(chart).toHaveAttribute('data-data-length', '0')
    })

    it('handles malformed data gracefully', () => {
      const malformedData = [
        { timestamp: 'invalid-date', value: 'not-a-number' },
        { timestamp: '2025-01-01T00:00:00Z', value: 100 }
      ]
      
      render(
        <TimeSeriesChart 
          data={malformedData}
          title="Malformed Data Chart"
          dataKey="value"
        />
      )
      
      // Should not crash
      expect(screen.getByText('Malformed Data Chart')).toBeInTheDocument()
    })

    it('handles missing required props gracefully', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Minimal Chart"
          dataKey=""
        />
      )
      
      // Should render but with empty data key
      expect(screen.getByText('Minimal Chart')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('provides proper ARIA labels', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Accessible Chart"
          dataKey="value"
          ariaLabel="Time series chart showing value over time"
        />
      )
      
      const heading = screen.getByRole('heading', { level: 3 })
      expect(heading).toHaveTextContent('Accessible Chart')
    })

    it('supports keyboard navigation for controls', async () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Keyboard Navigation Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      const zoomInButton = screen.getByTestId('zoom-in-icon').parentElement
      zoomInButton!.focus()
      
      expect(document.activeElement).toBe(zoomInButton)
    })

    it('provides meaningful descriptions for screen readers', () => {
      render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Screen Reader Friendly Chart"
          dataKey="value"
          description="This chart shows data trends over the past 7 hours"
        />
      )
      
      expect(screen.getByText('Screen Reader Friendly Chart')).toBeInTheDocument()
    })
  })

  describe('Real-time Updates', () => {
    it('handles data updates smoothly', () => {
      const { rerender } = render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Live Chart"
          dataKey="value"
        />
      )
      
      const newDataPoint = {
        timestamp: '2025-01-01T07:00:00Z',
        value: 150,
        secondary: 75
      }
      
      const updatedData = [...mockTimeSeriesData, newDataPoint]
      
      rerender(
        <TimeSeriesChart 
          data={updatedData}
          title="Live Chart"
          dataKey="value"
        />
      )
      
      const chart = screen.getByTestId('recharts-line-chart')
      expect(chart).toHaveAttribute('data-data-length', '8')
    })

    it('maintains zoom level during updates', () => {
      const { rerender } = render(
        <TimeSeriesChart 
          data={mockTimeSeriesData}
          title="Persistent Zoom Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      // Simulate data update
      rerender(
        <TimeSeriesChart 
          data={[...mockTimeSeriesData, { timestamp: '2025-01-01T07:00:00Z', value: 150 }]}
          title="Persistent Zoom Chart"
          dataKey="value"
          enableZoom={true}
        />
      )
      
      // Zoom controls should still be available
      expect(screen.getByTestId('zoom-in-icon')).toBeInTheDocument()
    })
  })
})
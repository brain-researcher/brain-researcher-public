'use client'

interface ThumbnailOptions {
  width?: number
  height?: number
  quality?: number
  format?: 'jpeg' | 'png' | 'webp'
  backgroundColor?: string
}

interface BrainMapThumbnailOptions extends ThumbnailOptions {
  slice?: 'middle' | 'axial' | 'coronal' | 'sagittal'
  colormap?: 'grayscale' | 'viridis' | 'plasma' | 'jet'
  contrast?: number
  brightness?: number
}

interface TableThumbnailOptions extends ThumbnailOptions {
  maxRows?: number
  maxCols?: number
  showHeaders?: boolean
  cellPadding?: number
}

interface GraphThumbnailOptions extends ThumbnailOptions {
  preserveAspectRatio?: boolean
  showAxes?: boolean
  showLegend?: boolean
}

export class ThumbnailGenerator {
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D

  constructor() {
    this.canvas = document.createElement('canvas')
    this.ctx = this.canvas.getContext('2d')!
  }

  /**
   * Generate thumbnail for brain map (NIfTI) files
   */
  async generateBrainMapThumbnail(
    imageUrl: string, 
    options: BrainMapThumbnailOptions = {}
  ): Promise<string> {
    const {
      width = 200,
      height = 200,
      quality = 0.8,
      format = 'jpeg',
      slice = 'middle',
      colormap = 'grayscale'
    } = options

    return new Promise((resolve, reject) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      
      img.onload = () => {
        this.canvas.width = width
        this.canvas.height = height
        
        // Clear canvas
        this.ctx.fillStyle = '#000000'
        this.ctx.fillRect(0, 0, width, height)
        
        // Calculate aspect ratio and positioning
        const scale = Math.min(width / img.width, height / img.height)
        const scaledWidth = img.width * scale
        const scaledHeight = img.height * scale
        const x = (width - scaledWidth) / 2
        const y = (height - scaledHeight) / 2
        
        // Draw image
        this.ctx.drawImage(img, x, y, scaledWidth, scaledHeight)
        
        // Apply colormap if needed (simplified implementation)
        if (colormap !== 'grayscale') {
          this.applyColormap(colormap)
        }
        
        // Add brain map indicator
        this.addTypeIndicator('🧠', 'brain-map')
        
        resolve(this.canvas.toDataURL(`image/${format}`, quality))
      }
      
      img.onerror = () => {
        // Generate placeholder for brain maps
        resolve(this.generatePlaceholder('brain-map', options))
      }
      
      img.src = imageUrl
    })
  }

  /**
   * Generate thumbnail for table data
   */
  async generateTableThumbnail(
    tableData: any[][],
    options: TableThumbnailOptions = {}
  ): Promise<string> {
    const {
      width = 200,
      height = 200,
      quality = 0.8,
      format = 'png',
      maxRows = 5,
      maxCols = 4,
      showHeaders = true
    } = options

    this.canvas.width = width
    this.canvas.height = height
    
    // Clear canvas with white background
    this.ctx.fillStyle = '#ffffff'
    this.ctx.fillRect(0, 0, width, height)
    
    if (!tableData || tableData.length === 0) {
      return this.generatePlaceholder('table', options)
    }

    // Calculate cell dimensions
    const padding = 10
    const cellWidth = (width - padding * 2) / maxCols
    const cellHeight = (height - padding * 2) / maxRows
    
    // Set up text style
    this.ctx.font = '10px Arial'
    this.ctx.textAlign = 'center'
    this.ctx.textBaseline = 'middle'
    
    // Draw table structure
    this.ctx.strokeStyle = '#e5e7eb'
    this.ctx.lineWidth = 1
    
    const rowsToShow = Math.min(maxRows, tableData.length)
    const colsToShow = Math.min(maxCols, tableData[0]?.length || 0)
    
    for (let row = 0; row < rowsToShow; row++) {
      for (let col = 0; col < colsToShow; col++) {
        const x = padding + col * cellWidth
        const y = padding + row * cellHeight
        
        // Draw cell border
        this.ctx.strokeRect(x, y, cellWidth, cellHeight)
        
        // Fill header row differently
        if (row === 0 && showHeaders) {
          this.ctx.fillStyle = '#f3f4f6'
          this.ctx.fillRect(x, y, cellWidth, cellHeight)
        }
        
        // Draw cell content
        if (tableData[row] && tableData[row][col] !== undefined) {
          this.ctx.fillStyle = '#374151'
          const text = String(tableData[row][col])
          const truncated = text.length > 8 ? text.substring(0, 6) + '...' : text
          this.ctx.fillText(truncated, x + cellWidth / 2, y + cellHeight / 2)
        }
      }
    }
    
    // Add table indicator
    this.addTypeIndicator('📊', 'table')
    
    return this.canvas.toDataURL(`image/${format}`, quality)
  }

  /**
   * Generate thumbnail for graph/chart images
   */
  async generateGraphThumbnail(
    imageUrl: string,
    options: GraphThumbnailOptions = {}
  ): Promise<string> {
    const {
      width = 200,
      height = 200,
      quality = 0.8,
      format = 'png',
      preserveAspectRatio = true
    } = options

    return new Promise((resolve, reject) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      
      img.onload = () => {
        this.canvas.width = width
        this.canvas.height = height
        
        // Clear canvas with white background
        this.ctx.fillStyle = '#ffffff'
        this.ctx.fillRect(0, 0, width, height)
        
        let drawWidth, drawHeight, x, y
        
        if (preserveAspectRatio) {
          const scale = Math.min(width / img.width, height / img.height)
          drawWidth = img.width * scale
          drawHeight = img.height * scale
          x = (width - drawWidth) / 2
          y = (height - drawHeight) / 2
        } else {
          drawWidth = width
          drawHeight = height
          x = 0
          y = 0
        }
        
        // Draw image
        this.ctx.drawImage(img, x, y, drawWidth, drawHeight)
        
        // Add graph indicator
        this.addTypeIndicator('📈', 'graph')
        
        resolve(this.canvas.toDataURL(`image/${format}`, quality))
      }
      
      img.onerror = () => {
        resolve(this.generatePlaceholder('graph', options))
      }
      
      img.src = imageUrl
    })
  }

  /**
   * Generate thumbnail for report/document files
   */
  async generateReportThumbnail(
    content: string,
    options: ThumbnailOptions = {}
  ): Promise<string> {
    const {
      width = 200,
      height = 200,
      quality = 0.8,
      format = 'png'
    } = options

    this.canvas.width = width
    this.canvas.height = height
    
    // Clear canvas with white background
    this.ctx.fillStyle = '#ffffff'
    this.ctx.fillRect(0, 0, width, height)
    
    // Add document border
    this.ctx.strokeStyle = '#d1d5db'
    this.ctx.lineWidth = 2
    this.ctx.strokeRect(10, 10, width - 20, height - 20)
    
    // Set up text style
    this.ctx.font = '12px Arial'
    this.ctx.fillStyle = '#374151'
    this.ctx.textAlign = 'left'
    this.ctx.textBaseline = 'top'
    
    // Draw text lines (simplified)
    const lines = content.split('\n').slice(0, 10)
    const lineHeight = 14
    const padding = 20
    
    for (let i = 0; i < Math.min(lines.length, 8); i++) {
      const y = padding + i * lineHeight
      const text = lines[i].length > 20 ? lines[i].substring(0, 18) + '...' : lines[i]
      
      // Draw line placeholder
      this.ctx.fillStyle = i === 0 ? '#111827' : '#6b7280'
      this.ctx.font = i === 0 ? 'bold 12px Arial' : '10px Arial'
      this.ctx.fillText(text || '─'.repeat(15), padding, y)
    }
    
    // Add report indicator
    this.addTypeIndicator('📄', 'report')
    
    return this.canvas.toDataURL(`image/${format}`, quality)
  }

  /**
   * Generate a placeholder thumbnail for unknown or failed types
   */
  private generatePlaceholder(
    type: string,
    options: ThumbnailOptions = {}
  ): string {
    const {
      width = 200,
      height = 200,
      quality = 0.8,
      format = 'png',
      backgroundColor = '#f3f4f6'
    } = options

    this.canvas.width = width
    this.canvas.height = height
    
    // Fill background
    this.ctx.fillStyle = backgroundColor
    this.ctx.fillRect(0, 0, width, height)
    
    // Add type indicator
    const icons = {
      'brain-map': '🧠',
      'statistical-map': '🧠',
      'table': '📊',
      'graph': '📈',
      'report': '📄',
      'metadata': '📋'
    }
    
    const icon = icons[type as keyof typeof icons] || '📁'
    this.addTypeIndicator(icon, type)
    
    return this.canvas.toDataURL(`image/${format}`, quality)
  }

  /**
   * Add a type indicator to the thumbnail
   */
  private addTypeIndicator(icon: string, type: string) {
    const size = 24
    const x = this.canvas.width - size - 8
    const y = 8
    
    // Draw background circle
    this.ctx.fillStyle = 'rgba(0, 0, 0, 0.7)'
    this.ctx.beginPath()
    this.ctx.arc(x + size / 2, y + size / 2, size / 2, 0, 2 * Math.PI)
    this.ctx.fill()
    
    // Draw icon
    this.ctx.font = '16px Arial'
    this.ctx.textAlign = 'center'
    this.ctx.textBaseline = 'middle'
    this.ctx.fillStyle = '#ffffff'
    this.ctx.fillText(icon, x + size / 2, y + size / 2)
  }

  /**
   * Apply colormap to canvas (simplified implementation)
   */
  private applyColormap(colormap: string) {
    const imageData = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height)
    const data = imageData.data
    
    for (let i = 0; i < data.length; i += 4) {
      const gray = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114
      
      switch (colormap) {
        case 'viridis':
          data[i] = Math.floor(gray * 0.267 / 255 * 255)     // R
          data[i + 1] = Math.floor(gray * 0.004 / 255 * 255) // G
          data[i + 2] = Math.floor(gray * 0.329 / 255 * 255) // B
          break
        case 'plasma':
          data[i] = Math.floor(gray * 0.050 / 255 * 255)     // R
          data[i + 1] = Math.floor(gray * 0.029 / 255 * 255) // G
          data[i + 2] = Math.floor(gray * 0.527 / 255 * 255) // B
          break
        case 'jet':
          if (gray < 64) {
            data[i] = 0
            data[i + 1] = 0
            data[i + 2] = Math.floor(128 + gray * 2)
          } else if (gray < 128) {
            data[i] = 0
            data[i + 1] = Math.floor((gray - 64) * 4)
            data[i + 2] = 255
          } else if (gray < 192) {
            data[i] = Math.floor((gray - 128) * 4)
            data[i + 1] = 255
            data[i + 2] = Math.floor(255 - (gray - 128) * 4)
          } else {
            data[i] = 255
            data[i + 1] = Math.floor(255 - (gray - 192) * 4)
            data[i + 2] = 0
          }
          break
      }
    }
    
    this.ctx.putImageData(imageData, 0, 0)
  }
}

// Utility functions
export function generateThumbnailFromUrl(
  url: string,
  type: string,
  options: ThumbnailOptions = {}
): Promise<string> {
  const generator = new ThumbnailGenerator()
  
  switch (type) {
    case 'brain-map':
    case 'statistical-map':
      return generator.generateBrainMapThumbnail(url, options as BrainMapThumbnailOptions)
    case 'graph':
      return generator.generateGraphThumbnail(url, options as GraphThumbnailOptions)
    default:
      return Promise.resolve((generator as any).generatePlaceholder(type, options))
  }
}

export function generateThumbnailFromData(
  data: any,
  type: string,
  options: ThumbnailOptions = {}
): Promise<string> {
  const generator = new ThumbnailGenerator()
  
  switch (type) {
    case 'table':
      return generator.generateTableThumbnail(data, options as TableThumbnailOptions)
    case 'report':
      return generator.generateReportThumbnail(data, options)
    default:
      return Promise.resolve((generator as any).generatePlaceholder(type, options))
  }
}

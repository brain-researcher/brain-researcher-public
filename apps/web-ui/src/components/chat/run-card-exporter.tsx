'use client'

import { useState } from 'react'
import { 
  Download, 
  FileJson, 
  FileText,
  QrCode,
  Copy,
  Check,
  Loader2,
  AlertCircle,
  Info
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogFooter, 
  DialogHeader, 
  DialogTitle 
} from '@/components/ui/dialog'
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue 
} from '@/components/ui/select'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/hooks/use-toast'
import { ChatRunCard } from '@/types/chat'
import { serviceEndpoints } from '@/lib/service-endpoints'
import type { ExportOptions } from '@/lib/evidence-rail-integration'

interface RunCardExporterProps {
  isOpen: boolean
  onClose: () => void
  runCard?: ChatRunCard
  jobId?: string
  onExport?: (format: ExportFormat, options: ExportOptions) => Promise<void>
}

type ExportFormat = 'json' | 'yaml' | 'pdf'

const formatInfo = {
  json: {
    icon: FileJson,
    name: 'JSON',
    description: 'Machine-readable format for programmatic use',
    size: 'Small (~5-20KB)',
    use: 'API integration, data processing'
  },
  yaml: {
    icon: FileText,
    name: 'YAML',
    description: 'Human-readable format for configuration',
    size: 'Small (~5-20KB)',
    use: 'Documentation, version control'
  },
  pdf: {
    icon: FileText,
    name: 'PDF',
    description: 'Publication-ready report with visualizations',
    size: 'Medium (~100KB-1MB)',
    use: 'Reports, presentations, archival'
  }
}

export function RunCardExporter({ 
  isOpen, 
  onClose, 
  runCard, 
  jobId, 
  onExport 
}: RunCardExporterProps) {
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('json')
  const [options, setOptions] = useState<ExportOptions>({
    includeArtifacts: true,
    includeProvenance: true,
    includeCitations: true,
    includeEnvironment: true,
    generateQR: false
  })
  const [isExporting, setIsExporting] = useState(false)
  const [shareUrl, setShareUrl] = useState<string>('')
  const [copied, setCopied] = useState(false)
  
  const { toast } = useToast()

  const handleExport = async () => {
    if (!jobId) {
      toast({
        title: "No Result Package Available",
        description: "Cannot export — no run ID found",
        variant: "destructive"
      })
      return
    }

    setIsExporting(true)
    
    try {
      if (onExport) {
        await onExport(selectedFormat, options)
      } else {
        // Fallback export using fetch
        const isPdf = selectedFormat === 'pdf'

        const params = new URLSearchParams(
          isPdf
            ? { format: 'pdf' }
            : {
                format: selectedFormat,
                includeArtifacts: String(options.includeArtifacts),
                includeProvenance: String(options.includeProvenance),
                includeCitations: String(options.includeCitations),
                includeEnvironment: String(options.includeEnvironment),
              },
        )

        const route = isPdf
          ? `/api/analyses/${jobId}/runcard/export?${params}`
          : `/api/analyses/${jobId}/observation/export?${params}`

        const response = await fetch(route, {
          method: 'GET',
          headers: { 'Accept': 'application/octet-stream' },
        })
        
        if (!response.ok) {
          throw new Error(`Export failed: ${response.statusText}`)
        }
        
        // Handle download
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = isPdf
          ? `result_package_${jobId}.pdf`
          : `observation_${jobId}.${selectedFormat}`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        window.URL.revokeObjectURL(url)
      }
      
      // Generate share URL if requested
      if (options.generateQR && jobId) {
        const shareResponse = await fetch(serviceEndpoints.orchestrator('/api/evidence/share'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            jobId, 
            format: selectedFormat,
            expires_in_hours: 24 
          })
        })
        
        if (shareResponse.ok) {
          const { share_url } = await shareResponse.json()
          setShareUrl(share_url)
        }
      }
      
      toast({
        title: "Export Successful",
        description: `Result Package exported as ${selectedFormat.toUpperCase()}`
      })
      
      // Keep modal open if QR code was generated
      if (!options.generateQR) {
        onClose()
      }
      
    } catch (error) {
      console.error('Export failed:', error)
      toast({
        title: "Export Failed",
        description: error.message || "Failed to export Result Package",
        variant: "destructive"
      })
    } finally {
      setIsExporting(false)
    }
  }

  const copyShareUrl = async () => {
    if (shareUrl) {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      toast({
        title: "Link Copied",
        description: "Share link copied to clipboard"
      })
    }
  }

  const getReproducibilityScore = () => {
    if (!runCard) return 0

    let score = 0
    if (options.includeEnvironment) score += 25
    if (options.includeProvenance) score += 25
    if (options.includeCitations) score += 20
    if (options.includeArtifacts) score += 20
    if (runCard.reproducibility?.randomSeed !== undefined) score += 10

    return Math.min(score, 100)
  }

  const reproScore = getReproducibilityScore()

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Export Result Package
          </DialogTitle>
          <DialogDescription>
            <span className="block">Methods · Parameters · Artifacts (for reproducibility)</span>
            <span className="mt-1 block">Create a reproducible results package containing all run metadata</span>
          </DialogDescription>
        </DialogHeader>
        
        <div className="space-y-6">
          {/* Format Selection */}
          <div>
            <h3 className="text-sm font-medium mb-3">Export Format</h3>
            <div className="grid grid-cols-3 gap-3">
              {(Object.entries(formatInfo) as [ExportFormat, typeof formatInfo.json][]).map(([format, info]) => {
                const Icon = info.icon
                return (
                  <Card 
                    key={format}
                    className={`cursor-pointer transition-all ${
                      selectedFormat === format 
                        ? 'ring-2 ring-primary' 
                        : 'hover:bg-muted/50'
                    }`}
                    onClick={() => setSelectedFormat(format)}
                  >
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Icon className="h-4 w-4" />
                        {info.name}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <p className="text-xs text-muted-foreground mb-1">
                        {info.description}
                      </p>
                      <div className="text-xs">
                        <Badge variant="secondary" className="text-[10px]">
                          {info.size}
                        </Badge>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>
          
          {/* Export Options */}
          <div>
            <h3 className="text-sm font-medium mb-3">Include in Export</h3>
            <div className="space-y-3">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="artifacts"
                  checked={options.includeArtifacts}
                  onCheckedChange={(checked) => 
                    setOptions(prev => ({ ...prev, includeArtifacts: Boolean(checked) }))
                  }
                />
                <label htmlFor="artifacts" className="text-sm">
                  Run artifacts and outputs
                </label>
              </div>
              
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="provenance"
                  checked={options.includeProvenance}
                  onCheckedChange={(checked) => 
                    setOptions(prev => ({ ...prev, includeProvenance: Boolean(checked) }))
                  }
                />
                <label htmlFor="provenance" className="text-sm">
                  Complete provenance graph
                </label>
              </div>
              
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="citations"
                  checked={options.includeCitations}
                  onCheckedChange={(checked) => 
                    setOptions(prev => ({ ...prev, includeCitations: Boolean(checked) }))
                  }
                />
                <label htmlFor="citations" className="text-sm">
                  Citations and references
                </label>
              </div>
              
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="environment"
                  checked={options.includeEnvironment}
                  onCheckedChange={(checked) => 
                    setOptions(prev => ({ ...prev, includeEnvironment: Boolean(checked) }))
                  }
                />
                <label htmlFor="environment" className="text-sm">
                  Environment and system info
                </label>
              </div>
              
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="qr"
                  checked={options.generateQR}
                  onCheckedChange={(checked) => 
                    setOptions(prev => ({ ...prev, generateQR: Boolean(checked) }))
                  }
                />
                <label htmlFor="qr" className="text-sm">
                  Generate shareable QR code
                </label>
              </div>
            </div>
          </div>
          
          {/* Reproducibility Score */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Info className="h-4 w-4" />
                Reproducibility Score
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full transition-all ${
                        reproScore >= 80 ? 'bg-green-600' :
                        reproScore >= 60 ? 'bg-yellow-600' : 'bg-red-600'
                      }`}
                      style={{ width: `${reproScore}%` }}
                    />
                  </div>
                </div>
                <span className={`text-sm font-bold ${
                  reproScore >= 80 ? 'text-green-600' :
                  reproScore >= 60 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {reproScore}%
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Higher scores indicate better reproducibility. Include more metadata to improve this score.
              </p>
            </CardContent>
          </Card>
          
          {/* Share URL Display */}
          {shareUrl && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <QrCode className="h-4 w-4" />
                  Shareable Link
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2">
                  <code className="flex-1 p-2 bg-muted rounded text-xs break-all">
                    {shareUrl}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={copyShareUrl}
                    disabled={copied}
                  >
                    {copied ? (
                      <Check className="h-3 w-3" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  This link will expire in 24 hours. Anyone with the link can view the Result Package.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
        
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button 
            onClick={handleExport}
            disabled={isExporting || !runCard}
            className="min-w-[100px]"
          >
            {isExporting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Download className="h-4 w-4 mr-2" />
                Export {selectedFormat.toUpperCase()}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

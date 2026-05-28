'use client'

import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ParameterSuggestions } from './parameter-suggestions'
import { MethodRecommendations } from './method-recommendations'
import { CopilotMessage, ParameterSuggestion, MethodRecommendation, CopilotState } from '@/types/copilot'
import { 
  Bot, 
  User, 
  Send, 
  Sparkles, 
  X, 
  Minimize2, 
  Maximize2,
  RefreshCw,
  MessageSquare
} from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'

interface CopilotPanelProps {
  isOpen: boolean
  isMinimized?: boolean
  messages: CopilotMessage[]
  suggestions: ParameterSuggestion[]
  recommendations: MethodRecommendation[]
  isLoading: boolean
  onClose: () => void
  onMinimize?: () => void
  onSendMessage: (message: string) => void
  onInsertParameter: (suggestion: ParameterSuggestion) => void
  onInsertMethod: (recommendation: MethodRecommendation) => void
  onClearMessages: () => void
  filters: {
    exposures: string[]
    domain: string
    function: string
    risk: string
  }
  onUpdateFilters: (updates: Partial<CopilotState['filters']>) => void
  className?: string
}

export function CopilotPanel({
  isOpen,
  isMinimized = false,
  messages,
  suggestions,
  recommendations,
  isLoading,
  onClose,
  onMinimize,
  onSendMessage,
  onInsertParameter,
  onInsertMethod,
  onClearMessages,
  filters = { exposures: [], domain: '', function: '', risk: '' },
  onUpdateFilters,
  className
}: CopilotPanelProps) {
  const [input, setInput] = useState('')
  const [activeTab, setActiveTab] = useState<'chat' | 'suggestions' | 'methods'>('suggestions')
  const exposures = Array.isArray(filters.exposures) ? filters.exposures : []
  const advancedOn = exposures.includes('advanced') || exposures.includes('internal')
  const ANY_OPTION = '__any__'

  const handleAdvancedToggle = (checked: boolean) => {
    onUpdateFilters({
      exposures: checked
        ? ['chat', 'pipeline', 'cli', 'advanced', 'internal']
        : ['chat'],
    })
  }

  const handleSend = () => {
    if (!input.trim() || isLoading) return
    onSendMessage(input)
    setInput('')
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!isOpen) return null

  if (isMinimized) {
    return (
      <div className="fixed bottom-3 right-3 z-50 sm:bottom-4 sm:right-4">
        <Button
          onClick={onMinimize}
          className="h-12 w-12 rounded-full shadow-lg"
        >
          <Bot className="h-6 w-6" />
        </Button>
      </div>
    )
  }

  return (
    <div
      className={`fixed inset-x-2 bottom-2 top-24 z-50 sm:bottom-4 sm:left-auto sm:right-4 sm:top-4 sm:w-80 ${className}`}
    >
      <Card className="h-full flex flex-col shadow-xl border-2">
        {/* Header */}
        <CardHeader className="pb-3 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <Bot className="h-4 w-4 text-primary" />
              </div>
              <div>
                <CardTitle className="text-sm">Copilot</CardTitle>
                <CardDescription className="text-xs">
                  AI-powered analysis assistance
                </CardDescription>
              </div>
            </div>
            
            <div className="flex items-center gap-1">
              {onMinimize && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onMinimize}
                  className="h-6 w-6 p-0"
                  aria-label="Minimize copilot"
                >
                  <Minimize2 className="h-3 w-3" />
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                className="h-6 w-6 p-0"
                aria-label="Close copilot"
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>

          {/* Filters */}
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-2">
              <Switch id="copilot-advanced" checked={advancedOn} onCheckedChange={handleAdvancedToggle} />
              <Label htmlFor="copilot-advanced" className="text-xs">Advanced/backends</Label>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div>
                <Label className="text-[11px] text-muted-foreground">Domain</Label>
                <Select
                  value={filters.domain || ANY_OPTION}
                  onValueChange={(v) => onUpdateFilters({ domain: v === ANY_OPTION ? '' : v })}
                >
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="any" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY_OPTION}>Any</SelectItem>
                    <SelectItem value="fmri">fMRI</SelectItem>
                    <SelectItem value="dmri">dMRI</SelectItem>
                    <SelectItem value="surface">Surface</SelectItem>
                    <SelectItem value="eeg">EEG</SelectItem>
                    <SelectItem value="ieeg">iEEG</SelectItem>
                    <SelectItem value="kg">KG</SelectItem>
                    <SelectItem value="datasets">Datasets</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Function</Label>
                <Select
                  value={filters.function || ANY_OPTION}
                  onValueChange={(v) => onUpdateFilters({ function: v === ANY_OPTION ? '' : v })}
                >
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="any" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY_OPTION}>Any</SelectItem>
                    <SelectItem value="preproc">Preproc</SelectItem>
                    <SelectItem value="glm">GLM</SelectItem>
                    <SelectItem value="connectivity">Connectivity</SelectItem>
                    <SelectItem value="qc">QC</SelectItem>
                    <SelectItem value="analysis">Analysis</SelectItem>
                    <SelectItem value="decoding">Decoding</SelectItem>
                    <SelectItem value="visualization">Viz</SelectItem>
                    <SelectItem value="report">Report</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Risk</Label>
                <Select
                  value={filters.risk || ANY_OPTION}
                  onValueChange={(v) => onUpdateFilters({ risk: v === ANY_OPTION ? '' : v })}
                >
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="any" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY_OPTION}>Any</SelectItem>
                    <SelectItem value="safe">Safe</SelectItem>
                    <SelectItem value="dangerous">Dangerous</SelectItem>
                    <SelectItem value="high_cost">High cost</SelectItem>
                    <SelectItem value="external_net">External net</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
              <Badge variant="secondary">Exposure: {filters.exposures.join(', ') || 'chat'}</Badge>
              {filters.risk && <Badge variant="outline">Risk: {filters.risk}</Badge>}
            </div>
          </div>
        </CardHeader>

        {/* Content */}
        <CardContent className="flex-1 overflow-hidden p-0">
          <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as any)} className="h-full">
            <TabsList className="grid w-full grid-cols-3 rounded-none border-b">
              <TabsTrigger value="suggestions" className="text-xs">
                <Sparkles className="h-3 w-3 mr-1" />
                Params
              </TabsTrigger>
              <TabsTrigger value="methods" className="text-xs">
                <MessageSquare className="h-3 w-3 mr-1" />
                Methods
              </TabsTrigger>
              <TabsTrigger value="chat" className="text-xs">
                <Bot className="h-3 w-3 mr-1" />
                Chat
              </TabsTrigger>
            </TabsList>

            <TabsContent value="suggestions" className="h-full mt-0">
              <div className="p-4 h-full overflow-y-auto">
                <ParameterSuggestions
                  suggestions={suggestions}
                  onInsert={onInsertParameter}
                />
              </div>
            </TabsContent>

            <TabsContent value="methods" className="h-full mt-0">
              <div className="p-4 h-full overflow-y-auto">
                <MethodRecommendations
                  recommendations={recommendations}
                  onInsert={onInsertMethod}
                />
              </div>
            </TabsContent>

            <TabsContent value="chat" className="h-full mt-0 flex flex-col">
              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Bot className="h-8 w-8 mx-auto mb-2" />
                    <p className="text-sm font-medium">Hi! I'm your AI copilot</p>
                    <p className="text-xs">
                      Ask me about parameters, analysis methods, or neuroimaging best practices
                    </p>
                  </div>
                ) : (
                  messages.map((message) => (
                    <div key={message.id} className={`flex gap-2 ${message.type === 'user' ? 'flex-row-reverse' : ''}`}>
                      <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
                        message.type === 'user'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted text-muted-foreground'
                      }`}>
                        {message.type === 'user' ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
                      </div>
                      
                      <div className={`flex-1 space-y-2 ${message.type === 'user' ? 'text-right' : ''}`}>
                        <div className={`inline-block max-w-[90%] p-2 rounded-lg text-sm ${
                          message.type === 'user'
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted'
                        }`}>
                          {message.content}
                        </div>
                        
                        {message.suggestions && message.suggestions.length > 0 && (
                          <div className="space-y-1">
                            <div className="text-xs font-medium">Suggested parameters:</div>
                            {message.suggestions.slice(0, 2).map((suggestion) => (
                              <Button
                                key={suggestion.id}
                                variant="outline"
                                size="sm"
                                onClick={() => onInsertParameter(suggestion)}
                                className="text-xs mr-2 mb-1"
                              >
                                {suggestion.name}: {String(suggestion.value)}
                              </Button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
                
                {isLoading && (
                  <div className="flex gap-2">
                    <div className="flex-shrink-0 w-6 h-6 rounded-full bg-muted flex items-center justify-center">
                      <Bot className="h-3 w-3" />
                    </div>
                    <div className="bg-muted p-2 rounded-lg">
                      <div className="flex items-center gap-1">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        <span className="text-sm">Thinking...</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <Separator />

              {/* Input area */}
              <div className="p-4 space-y-2">
                {messages.length > 0 && (
                  <div className="flex justify-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onClearMessages}
                      className="text-xs text-muted-foreground"
                    >
                      Clear chat
                    </Button>
                  </div>
                )}
                
                <div className="flex gap-2">
                  <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyPress}
                    placeholder="Ask me anything about neuroimaging..."
                    className="text-sm"
                    disabled={isLoading}
                  />
                  <Button
                    onClick={handleSend}
                    size="sm"
                    disabled={!input.trim() || isLoading}
                  >
                    <Send className="h-3 w-3" />
                  </Button>
                </div>
                
                <div className="text-xs text-muted-foreground text-center">
                  ⌘ + Enter to send
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}

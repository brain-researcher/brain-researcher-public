'use client'

import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Send, Loader2, Brain } from 'lucide-react'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface KnowledgeGraphChatModalProps {
  isOpen: boolean
  onClose: () => void
  conceptId?: string | null
  conceptLabel?: string
}

export function KnowledgeGraphChatModal({
  isOpen,
  onClose,
  conceptId,
  conceptLabel
}: KnowledgeGraphChatModalProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    setInput('')
    setIsLoading(true)

    // Add user message to chat
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])

    try {
      // Construct message with concept context if available
      const message = conceptId
        ? `Context: Asking about ${conceptLabel || conceptId}. Question: ${userMessage}`
        : userMessage

      // Call the chat API
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: message
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to get response from knowledge graph')
      }

      const data = await response.json()

      // Extract the response content
      const assistantMessage = data.message?.content || 'I could not find relevant information.'

      // Add assistant message to chat
      setMessages(prev => [...prev, { role: 'assistant', content: assistantMessage }])
    } catch (error) {
      console.error('Error querying knowledge graph:', error)
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error while searching the knowledge graph. Please try again.' }
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl h-[600px] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5" />
            Ask the Knowledge Graph
          </DialogTitle>
          <DialogDescription>
            {conceptId
              ? `Ask natural language questions about ${conceptLabel || conceptId} and the knowledge graph will provide answers.`
              : 'Ask natural language questions about the knowledge graph and get instant answers.'}
          </DialogDescription>
        </DialogHeader>

        {/* Chat Messages */}
        <ScrollArea className="flex-1 pr-4">
          <div className="space-y-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-64 text-center text-muted-foreground">
                <Brain className="h-12 w-12 mb-3 opacity-50" />
                <p className="text-sm">Start a conversation by asking a question below.</p>
                {conceptId && (
                  <p className="text-xs mt-2">
                    Your questions will be scoped to: <span className="font-medium">{conceptLabel}</span>
                  </p>
                )}
              </div>
            )}

            {messages.map((message, index) => (
              <div
                key={index}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] rounded-lg px-4 py-2 ${
                    message.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted'
                  }`}
                >
                  <p className="text-sm whitespace-pre-wrap">{message.content}</p>
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-muted rounded-lg px-4 py-2 flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm text-muted-foreground">Searching knowledge graph...</span>
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Input Area */}
        <div className="flex gap-2 pt-4 border-t">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask a question about the knowledge graph..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button onClick={handleSend} disabled={isLoading || !input.trim()} size="icon">
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            <span className="sr-only">Send message</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

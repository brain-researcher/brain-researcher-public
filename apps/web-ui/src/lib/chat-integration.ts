// Chat Interface Integration with LangGraph Agent


interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  attachments?: Attachment[]
  metadata?: {
    model?: string
    tokens?: number
    latency?: number
    tools_used?: string[]
  }
}

interface Attachment {
  id: string
  name: string
  type: string
  size: number
  url?: string
  data?: string
}

interface Thread {
  id: string
  title: string
  created_at: Date
  updated_at: Date
  message_count: number
  status: 'active' | 'archived'
}

interface StreamEvent {
  type: 'message' | 'tool_call' | 'error' | 'done'
  data: any
}

class ChatIntegration {
  private baseUrl: string
  private threadId: string | null = null
  private eventSource: EventSource | null = null
  private eventSourceClosedGracefully = false
  private messageQueue: Message[] = []
  
  constructor(baseUrl: string = '') {
    this.baseUrl = baseUrl
  }

  /**
   * Create a new chat thread
   */
  async createThread(title?: string): Promise<Thread> {
    const response = await fetch(`${this.baseUrl}/api/threads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title || 'New Chat' })
    })
    
    if (!response.ok) {
      throw new Error(`Failed to create thread: ${response.statusText}`)
    }
    
    const thread = await response.json()
    this.threadId = thread.id
    return thread
  }

  /**
   * Get thread history
   */
  async getThreadHistory(threadId: string, limit: number = 50): Promise<Message[]> {
    const response = await fetch(
      `${this.baseUrl}/api/threads/${threadId}/messages?limit=${limit}`
    )
    
    if (!response.ok) {
      throw new Error(`Failed to get thread history: ${response.statusText}`)
    }
    
    const data = await response.json()
    return data.messages
  }

  /**
   * Send a message and stream the response
   */
  async sendMessage(
    content: string,
    attachments?: Attachment[],
    onStream?: (event: StreamEvent) => void
  ): Promise<void> {
    if (!this.threadId) {
      await this.createThread()
    }
    
    // Send the message
    const response = await fetch(
      `${this.baseUrl}/api/threads/${this.threadId}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          attachments,
          stream: true
        })
      }
    )
    
    if (!response.ok) {
      throw new Error(`Failed to send message: ${response.statusText}`)
    }
    
    const { message_id } = await response.json()
    
    // Set up SSE for streaming response
    if (onStream) {
      this.streamResponse(message_id, onStream)
    }
  }

  /**
   * Stream response using Server-Sent Events
   */
  private streamResponse(messageId: string, onStream: (event: StreamEvent) => void) {
    const url = `${this.baseUrl}/api/threads/${this.threadId}/stream?message_id=${messageId}`
    
    // Close existing connection if any
    if (this.eventSource) {
      this.eventSource.close()
    }
    
    this.eventSourceClosedGracefully = false

    this.eventSource = new EventSource(url)
    
    this.eventSource.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        onStream({
          type: 'message',
          data
        })
      } catch (error) {
        console.error('Failed to parse SSE message:', error)
      }
    }
    
    this.eventSource.addEventListener('tool_call', (event: any) => {
      onStream({
        type: 'tool_call',
        data: JSON.parse(event.data)
      })
    })
    
    this.eventSource.addEventListener('done', (event: any) => {
      onStream({
        type: 'done',
        data: JSON.parse(event.data)
      })
      this.eventSourceClosedGracefully = true
      this.eventSource?.close()
      this.eventSource = null
    })

    this.eventSource.onerror = (error: any) => {
      const readyState = this.eventSource?.readyState
      const closed = readyState === EventSource.CLOSED || readyState === 2

      if (this.eventSourceClosedGracefully || closed) {
        console.debug('SSE connection closed after completion')
      } else {
        console.error('SSE error:', error)
        onStream({
          type: 'error',
          data: { error: 'Connection lost' }
        })
      }
      this.eventSource?.close()
      this.eventSource = null
      this.eventSourceClosedGracefully = false
    }
  }

  /**
   * Upload file attachment
   */
  async uploadAttachment(file: File): Promise<Attachment> {
    const formData = new FormData()
    formData.append('file', file)
    
    const response = await fetch(`${this.baseUrl}/api/attachments`, {
      method: 'POST',
      body: formData
    })
    
    if (!response.ok) {
      throw new Error(`Failed to upload attachment: ${response.statusText}`)
    }
    
    return await response.json()
  }

  /**
   * Execute a tool directly
   */
  async executeTool(
    toolName: string,
    parameters: any,
    onProgress?: (progress: number) => void
  ): Promise<any> {
    const response = await fetch(`${this.baseUrl}/api/tools/${toolName}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parameters })
    })
    
    if (!response.ok) {
      throw new Error(`Failed to execute tool: ${response.statusText}`)
    }
    
    const { job_id } = await response.json()
    
    // Poll for job status
    return this.pollJobStatus(job_id, onProgress)
  }

  /**
   * Poll job status
   */
  private async pollJobStatus(
    jobId: string,
    onProgress?: (progress: number) => void
  ): Promise<any> {
    const pollInterval = 1000 // 1 second
    const maxAttempts = 180 // 3 minutes max
    let attempts = 0
    
    while (attempts < maxAttempts) {
      const response = await fetch(`${this.baseUrl}/api/analyses/${jobId}`)
      
      if (!response.ok) {
        throw new Error(`Failed to get job status: ${response.statusText}`)
      }
      
      const payload = await response.json()
      const job = payload?.job ?? payload
      
      if (onProgress && job.progress) {
        onProgress(job.progress)
      }
      
      if (job.status === 'completed') {
        return job.result
      }
      
      if (job.status === 'failed') {
        throw new Error(job.error || 'Job failed')
      }
      
      attempts++
      await new Promise(resolve => setTimeout(resolve, pollInterval))
    }
    
    throw new Error('Job timed out')
  }

  /**
   * Get available tools
   */
  async getAvailableTools(): Promise<any[]> {
    const response = await fetch(`${this.baseUrl}/api/tools`)
    
    if (!response.ok) {
      throw new Error(`Failed to get tools: ${response.statusText}`)
    }
    
    const data = await response.json()
    return data.tools
  }

  /**
   * Clean up resources
   */
  cleanup() {
    if (this.eventSource) {
      this.eventSource.close()
      this.eventSource = null
    }
  }
}

// React hooks for chat integration
import { useState, useEffect, useCallback, useRef } from 'react'

export function useChatIntegration(baseUrl?: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentThread, setCurrentThread] = useState<Thread | null>(null)
  const [error, setError] = useState<string | null>(null)
  
  const chatRef = useRef<ChatIntegration | null>(null)
  
  useEffect(() => {
    chatRef.current = new ChatIntegration(baseUrl)
    
    return () => {
      chatRef.current?.cleanup()
    }
  }, [baseUrl])
  
  const createThread = useCallback(async (title?: string) => {
    try {
      const thread = await chatRef.current!.createThread(title)
      setCurrentThread(thread)
      setMessages([])
      return thread
    } catch (error) {
      setError(error.message)
      throw error
    }
  }, [])
  
  const loadThread = useCallback(async (threadId: string) => {
    try {
      const history = await chatRef.current!.getThreadHistory(threadId)
      setMessages(history)
    } catch (error) {
      setError(error.message)
      throw error
    }
  }, [])
  
  const sendMessage = useCallback(async (
    content: string,
    attachments?: Attachment[]
  ) => {
    if (!chatRef.current) return
    
    setIsStreaming(true)
    setError(null)
    
    // Add user message immediately
    const userMessage: Message = {
      id: `msg_${Date.now()}`,
      role: 'user',
      content,
      timestamp: new Date(),
      attachments
    }
    
    setMessages(prev => [...prev, userMessage])
    
    // Create assistant message placeholder
    const assistantMessage: Message = {
      id: `msg_${Date.now() + 1}`,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    
    setMessages(prev => [...prev, assistantMessage])
    
    try {
      await chatRef.current.sendMessage(content, attachments, (event) => {
        switch (event.type) {
          case 'message':
            // Update assistant message content
            setMessages(prev => {
              const newMessages = [...prev]
              const lastMessage = newMessages[newMessages.length - 1]
              if (lastMessage.role === 'assistant') {
                lastMessage.content = event.data.content || lastMessage.content
                if (event.data.metadata) {
                  lastMessage.metadata = event.data.metadata
                }
              }
              return newMessages
            })
            break
            
          case 'tool_call':
            // Add tool call information to metadata
            setMessages(prev => {
              const newMessages = [...prev]
              const lastMessage = newMessages[newMessages.length - 1]
              if (lastMessage.role === 'assistant') {
                lastMessage.metadata = {
                  ...lastMessage.metadata,
                  tools_used: [
                    ...(lastMessage.metadata?.tools_used || []),
                    event.data.tool_name
                  ]
                }
              }
              return newMessages
            })
            break
            
          case 'done':
            setIsStreaming(false)
            break
            
          case 'error':
            setError(event.data.error)
            setIsStreaming(false)
            break
        }
      })
    } catch (error) {
      setError(error.message)
      setIsStreaming(false)
      
      // Remove assistant message on error
      setMessages(prev => prev.slice(0, -1))
    }
  }, [])
  
  const uploadFile = useCallback(async (file: File) => {
    if (!chatRef.current) return null
    
    try {
      return await chatRef.current.uploadAttachment(file)
    } catch (error) {
      setError(error.message)
      throw error
    }
  }, [])
  
  return {
    messages,
    isStreaming,
    currentThread,
    error,
    createThread,
    loadThread,
    sendMessage,
    uploadFile
  }
}

// Export types and integration
export { ChatIntegration }
export type { Message, Attachment, Thread, StreamEvent }

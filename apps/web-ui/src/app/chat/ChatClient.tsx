'use client'

import { LinearChat } from '@/components/chat/LinearChat'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string
}

interface User {
  id?: string
  name?: string | null
  email?: string | null
  image?: string | null
  role?: string
  provider?: string
}

interface ChatClientProps {
  user: User
  initialMessages: Message[]
  accessToken?: string
  initialPrompt?: string
  systemPrompt?: string
  pipeline?: string
  datasetId?: string
  scenarioId?: string
  threadId: string
}

export default function ChatClient({
  // user, accessToken, threadId, initialMessages available for future API calls
  initialPrompt,
  systemPrompt,
  pipeline,
  datasetId,
  scenarioId,
}: ChatClientProps) {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <LinearChat
          initialPrompt={initialPrompt}
          systemPrompt={systemPrompt}
          pipeline={pipeline}
          datasetId={datasetId}
          scenarioId={scenarioId || undefined}
        />
      </div>
    </NavigationWrapper>
  )
}

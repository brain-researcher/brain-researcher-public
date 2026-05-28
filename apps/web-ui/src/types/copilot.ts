export interface ParameterSuggestion {
  id: string
  name: string
  value: string | number
  description: string
  category: 'preprocessing' | 'analysis' | 'statistics' | 'visualization' | 'backend'
  reasoning: string
  confidence: number // 0-1
  source: 'dataset_metadata' | 'best_practice' | 'literature' | 'backend'
  citation?: string
}

export interface MethodRecommendation {
  id: string
  name: string
  description: string
  category: 'preprocessing' | 'first_level' | 'group_level' | 'connectivity' | 'machine_learning'
  suitability: number // 0-1 how suitable for current context
  reasoning: string
  parameters: ParameterSuggestion[]
  prerequisites?: string[]
  example_prompt?: string
}

export interface CopilotMessage {
  id: string
  type: 'user' | 'copilot'
  content: string
  timestamp: Date
  suggestions?: ParameterSuggestion[]
  recommendations?: MethodRecommendation[]
}

export interface CopilotContext {
  selectedDataset?: string
  analysisType?: string
  currentPrompt?: string
  userExperience?: 'beginner' | 'intermediate' | 'expert'
}

export interface CopilotState {
  isOpen: boolean
  messages: CopilotMessage[]
  context: CopilotContext
  suggestions: ParameterSuggestion[]
  recommendations: MethodRecommendation[]
  isLoading: boolean
  filters: {
    exposures: string[]
    domain: string
    function: string
    risk: string
  }
}

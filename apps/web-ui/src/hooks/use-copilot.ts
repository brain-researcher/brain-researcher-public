'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  CopilotMessage,
  CopilotState,
  CopilotContext,
  ParameterSuggestion,
  MethodRecommendation,
} from '@/types/copilot'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'

type RawBackendSuggestion = {
  name: string
  description?: string
  reason: string
  score?: number
  autocomplete?: Record<string, unknown>
}

type RawBackendMethod = {
  id?: string
  intent_id?: string
  name: string
  description: string
  reason: string
  score?: number
  parameters?: Array<{
    name: string
    description?: string
    value?: string | number | boolean | null
    default?: string | number | boolean | null
  }>
}

type BackendSuggestionBundle = {
  suggestions: ParameterSuggestion[]
  recommendations: MethodRecommendation[]
}

const INTERNAL_REASONING_SENTENCE_RE =
  /\b(the user\b|i should\b|i need to\b|for this interaction\b|no specialized\b.*\bneeded\b|i captured your request\b|respond with a friendly greeting\b)/i
const GREETING_PROMPT_RE = /^\s*(hi|hello|hey|yo)\b/i

const postProcessCopilotReply = (raw: string, userPrompt: string): string => {
  const text = raw.trim()
  if (!text) return text

  const segments = text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((segment) => segment.trim())
    .filter(Boolean)

  if (segments.length === 0) return text

  const filtered = segments.filter(
    (segment) => !INTERNAL_REASONING_SENTENCE_RE.test(segment),
  )

  if (filtered.length === segments.length) {
    return text
  }

  const cleaned = filtered.join(' ').replace(/\s+/g, ' ').trim()
  if (cleaned) {
    return cleaned
  }

  if (GREETING_PROMPT_RE.test(userPrompt.trim())) {
    return 'Hi! How can I help with your neuroimaging analysis today?'
  }

  return 'I can help with parameter suggestions, method recommendations, and analysis planning. Share your goal, dataset, or pipeline.'
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const toTitleCase = (value: string): string =>
  value
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((segment) => `${segment[0]?.toUpperCase()}${segment.slice(1).toLowerCase()}`)
    .join(' ')

const mapBackendMethodCategory = (name: string): MethodRecommendation['category'] => {
  const key = name.toLowerCase()

  if (/(slice|motion|smooth|preproc|denoise|distortion|template|normaliz|fmriprep)/.test(key)) {
    return 'preprocessing'
  }
  if (/(hrf|glm|design|contrast|beta|tstat|first)/.test(key)) {
    return 'first_level'
  }
  if (/(group|seed|ica|connect|connectivity|parcellation|bandpass|graph)/.test(key)) {
    return 'connectivity'
  }
  if (/(fdr|fwer|cluster|threshold|pval|p-value|fwe|alpha)/.test(key)) {
    return 'group_level'
  }
  if (/(ml|decode|svm|classifier|random|ridge|lasso|xgboost)/.test(key)) {
    return 'machine_learning'
  }
  return 'first_level'
}

const mapBackendSuggestionValue = (suggestion: RawBackendSuggestion): string | number => {
  const autocomplete = isRecord(suggestion.autocomplete) ? suggestion.autocomplete : {}
  const directValue = autocomplete[suggestion.name]
  if (directValue !== undefined) {
    return typeof directValue === 'string' || typeof directValue === 'number'
      ? directValue
      : JSON.stringify(directValue)
  }

  const firstValue = Object.values(autocomplete)[0]
  if (firstValue === undefined) {
    return ''
  }

  return typeof firstValue === 'string' || typeof firstValue === 'number'
    ? firstValue
    : JSON.stringify(firstValue)
}

const mapBackendToSuggestion = (s: RawBackendSuggestion): ParameterSuggestion => ({
  id: s.name,
  name: s.name,
  value: mapBackendSuggestionValue(s),
  description: s.description || s.reason,
  category: 'backend',
  reasoning: s.reason,
  confidence: Math.min(1, Math.max(0, (s.score ?? 1) / 3)),
  source: 'backend',
})

const mapBackendToRecommendation = (
  s: RawBackendSuggestion,
  index: number,
): MethodRecommendation => {
  const paramsSource = isRecord(s.autocomplete) ? s.autocomplete : {}
  const paramEntries = Object.entries(paramsSource).slice(0, 3)
  const category = mapBackendMethodCategory(s.name)
  const methodConfidence = Math.min(1, Math.max(0.35, (s.score ?? 1.4) / 3))
  const title = toTitleCase(s.name)

  const parameters: ParameterSuggestion[] = paramEntries.map(([key, value], paramIndex) => ({
    id: `backend-param-${index}-${paramIndex}`,
    name: key,
    value: typeof value === 'string' || typeof value === 'number'
      ? value
      : JSON.stringify(value),
    description: `Parameter for ${title}`,
    category: 'analysis',
    reasoning: s.reason,
    confidence: methodConfidence,
    source: 'backend',
  }))

  return {
    id: `backend-method-${index}-${s.name}`,
    name: title,
    description: s.description || s.reason,
    category,
    suitability: methodConfidence,
    reasoning: s.reason,
    parameters,
    example_prompt: parameters.length > 0
      ? parameters.map((entry) => `${entry.name}=${entry.value}`).join(' ')
      : undefined,
  }
}

const mapBackendBundle = (suggestions: RawBackendSuggestion[]): BackendSuggestionBundle => {
  const mappedSuggestions = suggestions.map(mapBackendToSuggestion)
  const mappedRecommendations = suggestions.map(mapBackendToRecommendation)

  return {
    suggestions: mappedSuggestions,
    recommendations: mappedRecommendations.slice(0, 4),
  }
}

const mapBackendMethods = (
  methods: RawBackendMethod[] | undefined,
): MethodRecommendation[] => {
  if (!Array.isArray(methods) || methods.length === 0) return []

  return methods.slice(0, 6).map((method, index) => {
    const confidence = Math.min(1, Math.max(0.35, (method.score ?? 1.6) / 3))
    const category = mapBackendMethodCategory(method.intent_id || method.name)
    const parameters: ParameterSuggestion[] = (method.parameters || []).slice(0, 4).map((param, pidx) => {
      const chosenValue = param.value ?? param.default ?? ''
      return {
        id: `backend-method-param-${index}-${pidx}`,
        name: param.name,
        value: typeof chosenValue === 'string' || typeof chosenValue === 'number'
          ? chosenValue
          : String(chosenValue),
        description: param.description || `Parameter for ${method.name}`,
        category: 'analysis',
        reasoning: method.reason || method.description,
        confidence,
        source: 'backend',
      }
    })

    return {
      id: method.id || method.intent_id || `backend-method-${index}`,
      name: method.name,
      description: method.description,
      category,
      suitability: confidence,
      reasoning: method.reason || method.description,
      parameters,
      example_prompt: parameters.length
        ? parameters.map((entry) => `${entry.name}=${entry.value}`).join(' ')
        : undefined,
    }
  })
}

export function useCopilot() {
  const lastBootstrapRequestKey = useRef<string | null>(null)
  const [state, setState] = useState<CopilotState>({
    isOpen: false,
    messages: [],
    context: {},
    suggestions: [],
    recommendations: [],
    isLoading: false,
    filters: {
      exposures: ['chat'],
      domain: '',
      function: '',
      risk: '',
    },
  })

  const updateContext = useCallback((updates: Partial<CopilotContext>) => {
    setState(prev => ({
      ...prev,
      context: { ...prev.context, ...updates },
    }))
  }, [])

  const toggleCopilot = useCallback(() => {
    setState(prev => ({ ...prev, isOpen: !prev.isOpen }))
  }, [])

  const sendMessage = useCallback(async (content: string) => {
    const userMessage: CopilotMessage = {
      id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type: 'user',
      content,
      timestamp: new Date()
    }

    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMessage],
      isLoading: true
    }))

    try {
      let backendSuggestions: ParameterSuggestion[] | undefined
      let backendRecommendations: MethodRecommendation[] | undefined
      let backendError: string | null = null

      try {
        const res = await brainResearcherAPI.copilotSuggest(
          content,
          {},
          5,
          {
            exposures: state.filters.exposures,
            domain: state.filters.domain || undefined,
            func: state.filters.function || undefined,
            risk: state.filters.risk || undefined,
          }
        )
        const bundle = mapBackendBundle(res?.suggestions || [])
        const methodList = mapBackendMethods(res?.methods)
        backendSuggestions = bundle.suggestions
        backendRecommendations = methodList.length ? methodList : bundle.recommendations
      } catch (error) {
        backendError = error instanceof Error ? error.message : 'unknown error'
      }

      let response: string
      try {
        response = await brainResearcherAPI.chat(content, { copilot: true })
        response = postProcessCopilotReply(response, content)
      } catch (error) {
        const detail = error instanceof Error ? error.message : 'chat backend unavailable'
        response = `Copilot backend unavailable: ${detail}`
      }

      const chosenSuggestions = (backendSuggestions?.length
        ? backendSuggestions
        : state.suggestions
      ).filter((suggestion) => suggestion.confidence > 0.45).slice(0, 3)

      const chosenRecommendations = (backendRecommendations?.length
        ? backendRecommendations
        : state.recommendations
      ).slice(0, 3)

      const contentWithBackendStatus = backendError
        ? `${response}\n\n(Params/Methods backend unavailable: ${backendError})`
        : response

      const copilotMessage: CopilotMessage = {
        id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        type: 'copilot',
        content: contentWithBackendStatus,
        timestamp: new Date(),
        suggestions: chosenSuggestions,
        recommendations: chosenRecommendations,
      }

      setState(prev => ({
        ...prev,
        suggestions: backendSuggestions?.length ? backendSuggestions : prev.suggestions,
        recommendations: backendRecommendations?.length ? backendRecommendations : prev.recommendations,
        messages: [...prev.messages, copilotMessage],
        isLoading: false
      }))
    } catch {
      setState(prev => ({
        ...prev,
        isLoading: false
      }))
    }
  }, [state.suggestions, state.recommendations, state.filters])

  const setFilters = useCallback((updates: Partial<CopilotState['filters']>) => {
    setState(prev => ({
      ...prev,
      filters: { ...prev.filters, ...updates }
    }))
  }, [])

  const insertParameter = useCallback((suggestion: ParameterSuggestion): string => {
    return `${suggestion.name}=${suggestion.value}`
  }, [])

  const insertMethod = useCallback((recommendation: MethodRecommendation): string => {
    return recommendation.example_prompt || ''
  }, [])

  const clearMessages = useCallback(() => {
    setState(prev => ({ ...prev, messages: [] }))
  }, [])

  useEffect(() => {
    if (!state.isOpen) return

    const query = state.context.currentPrompt?.trim() || 'fMRI preprocessing and analysis'
    const requestKey = JSON.stringify({
      query,
      exposures: state.filters.exposures,
      domain: state.filters.domain,
      func: state.filters.function,
      risk: state.filters.risk,
      dataset: state.context.selectedDataset,
      analysisType: state.context.analysisType,
    })

    if (lastBootstrapRequestKey.current === requestKey) return
    lastBootstrapRequestKey.current = requestKey

    brainResearcherAPI
      .copilotSuggest(query, {
        dataset_id: state.context.selectedDataset,
        analysis_type: state.context.analysisType,
      }, 8, {
        exposures: state.filters.exposures,
        domain: state.filters.domain || undefined,
        func: state.filters.function || undefined,
        risk: state.filters.risk || undefined,
      })
      .then((res: { suggestions?: Array<RawBackendSuggestion>; methods?: Array<RawBackendMethod> }) => {
        const list = res?.suggestions || []
        const backendMethods = mapBackendMethods(res?.methods)
        if (list.length === 0 && backendMethods.length === 0) return

        const bundle = mapBackendBundle(list)
        setState(prev => ({
          ...prev,
          suggestions: bundle.suggestions.length ? bundle.suggestions : prev.suggestions,
          recommendations: backendMethods.length
            ? backendMethods
            : bundle.recommendations.length
              ? bundle.recommendations
              : prev.recommendations,
        }))
      })
      .catch(() => {
        // keep existing suggestions/recommendations
      })
  }, [
    state.isOpen,
    state.filters.exposures,
    state.filters.domain,
    state.filters.function,
    state.filters.risk,
    state.context.selectedDataset,
    state.context.analysisType,
    state.context.currentPrompt,
  ])

  return {
    ...state,
    updateContext,
    toggleCopilot,
    sendMessage,
    insertParameter,
    insertMethod,
    clearMessages,
    setFilters,
  }
}

import rawScenarioData from './chat_scenarios.json'

export const SCENARIO_IDS = [
  'encoding_model_designer',
  'model_size_suggester',
  'construct_to_task_dataset',
  'study_design_sanity_check',
  'paper_to_pipeline',
  'run_card_to_methods',
  'graph_analysis_designer'
] as const

export type ChatScenarioId = (typeof SCENARIO_IDS)[number]

interface RawScenario {
  title: string
  description: string
  system_prompt: string
  starter_user_message: string
}

export interface ChatScenarioConfig {
  id: ChatScenarioId
  title: string
  description: string
  systemPrompt: string
  starterUserMessage: string
}

const scenarioEntries = rawScenarioData as Record<string, RawScenario>

export const CHAT_SCENARIOS: Record<ChatScenarioId, ChatScenarioConfig> = SCENARIO_IDS.reduce(
  (acc, scenarioId) => {
    const raw = scenarioEntries[scenarioId]
    if (raw) {
      acc[scenarioId] = {
        id: scenarioId,
        title: raw.title,
        description: raw.description,
        systemPrompt: raw.system_prompt,
        starterUserMessage: raw.starter_user_message
      }
    }
    return acc
  },
  {} as Record<ChatScenarioId, ChatScenarioConfig>
)

export function getChatScenario(id?: string | null): ChatScenarioConfig | undefined {
  if (!id) return undefined
  return CHAT_SCENARIOS[id as ChatScenarioId]
}

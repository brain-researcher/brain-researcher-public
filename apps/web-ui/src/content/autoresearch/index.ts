import rawAutoresearchContent from './autoresearch-content.json'
import type { AutoresearchContent } from './types'

export const autoresearchContent = rawAutoresearchContent as AutoresearchContent

export type {
  AgendaDirection,
  AgendaQuestion,
  AnchorPaper,
  AutoresearchContent,
  NeuroimagingStartingQuestion,
  NeuroimagingTopic,
  ProgramId,
  ResearchProgram,
} from './types'

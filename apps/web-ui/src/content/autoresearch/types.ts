export type ProgramId =
  | 'neuroimaging'
  | 'bci'
  | 'behavior'
  | 'mechanisms'
  | 'intervention'

export interface AnchorPaper {
  title: string
  citation: string
  venue?: string
  url: string
}

export interface AgendaQuestion {
  title: string
}

export interface AgendaDirection {
  id: string
  title: string
  changed: string
  open: string
  anchors: AnchorPaper[]
  questions: AgendaQuestion[]
  br_entry: string
}

export interface ResearchProgram {
  short: string
  title: string
  copy: string
  big_questions: string[]
  directions?: AgendaDirection[]
  agenda_directions?: AgendaDirection[]
}

export interface NeuroimagingTopic {
  id: string
  name: string
  anchors: AnchorPaper[]
  question_count: number
  public_count: number
}

export interface NeuroimagingStartingQuestion {
  id: string
  topic: string
  question: string
  data_label: string
  citation: string
  paper_title: string
  paper_url: string
  source_question: string
  why: string
  origin: string
  score: number | null
  route: string
}

export interface PublicRecordLink {
  copy: string
  href: string
  link_label: string
}

export interface Mission {
  title: string
  intro: string
  participation: string
  validation: string
}

export interface FutureDirection {
  eyebrow: string
  title: string
  body: string[]
}

export interface ProposalSubmission {
  subject: string
  disclosure: string
  return_copy: string
  default_return_url: string
}

export interface AutoresearchContent {
  schema_version: 'br-autoresearch-public-content-v1'
  mission: Mission
  public_record: PublicRecordLink
  future_direction: FutureDirection
  proposal_submission: ProposalSubmission
  program_order: ProgramId[]
  programs: Record<ProgramId, ResearchProgram>
  neuroimaging_topics: NeuroimagingTopic[]
  neuroimaging_starting_questions: NeuroimagingStartingQuestion[]
}

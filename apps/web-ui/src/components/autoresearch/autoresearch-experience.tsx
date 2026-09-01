'use client'

import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useMemo, useRef, useState } from 'react'
import { ArrowRight, ChevronRight, Search } from 'lucide-react'

import { AgendaDirectionDetail } from '@/components/autoresearch/agenda-direction-detail'
import { StartingQuestion } from '@/components/autoresearch/starting-question'
import { ResponsiveFooter } from '@/components/responsive/ResponsiveContainer'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { autoresearchContent } from '@/content/autoresearch'
import type {
  AgendaDirection,
  NeuroimagingTopic,
  ProgramId,
  ResearchProgram,
} from '@/content/autoresearch'

interface AutoresearchExperienceProps {
  proposalReturnUrl?: string
}

interface ProposalDraft {
  question: string
  why: string
  dataRoute: string
  area: string
  name: string
  email: string
}

const content = autoresearchContent

const processSteps = [
  ['01', 'Submit', 'Share a scientific question, why it matters, and any data that may help.'],
  ['02', 'Refine together', 'Clarify the first exploration with the proposing researchers.'],
  ['03', 'Explore', 'BR investigates the question and returns evidence for review.'],
  ['04', 'Review', 'Check assumptions, interpretations, and unproductive directions.'],
  ['05', 'Choose a next step', 'Close, reframe, or plan the next study or experiment.'],
] as const

const defaultProposalDestination = 'https://formsubmit.co/zijiao@stanford.edu'

function directionsFor(program: ResearchProgram): AgendaDirection[] {
  return program.agenda_directions ?? program.directions ?? []
}

function isProgramId(value: string | null): value is ProgramId {
  return Boolean(value && content.program_order.includes(value as ProgramId))
}

function hasTopic(value: string | null): value is string {
  return Boolean(value && content.neuroimaging_topics.some((topic) => topic.id === value))
}

export function AutoresearchExperience({
  proposalReturnUrl,
}: AutoresearchExperienceProps) {
  const router = useRouter()
  const pathname = usePathname() || '/autoresearch'
  const searchParams = useSearchParams()
  const requestedProgram = searchParams.get('program')
  const initialProgram: ProgramId = isProgramId(requestedProgram)
    ? requestedProgram
    : content.program_order[0]
  const initialProgramDirections = directionsFor(content.programs[initialProgram])
  const requestedDirection = searchParams.get('direction')
  const initialDirection = initialProgramDirections.some((direction) => direction.id === requestedDirection)
    ? requestedDirection!
    : initialProgramDirections[0]?.id ?? ''
  const requestedTopic = searchParams.get('topic')
  const initialTopic = hasTopic(requestedTopic)
    ? requestedTopic
    : content.neuroimaging_topics[0]?.id ?? ''
  const formReturnUrl = proposalReturnUrl?.trim() || content.proposal_submission.default_return_url
  const submissionStatus = searchParams.get('submitted') === '1'
    ? content.proposal_submission.return_copy
    : content.proposal_submission.disclosure

  const [activeProgram, setActiveProgram] = useState<ProgramId>(initialProgram)
  const [activeDirectionId, setActiveDirectionId] = useState(initialDirection)
  const [selectedTopicId, setSelectedTopicId] = useState(initialTopic)
  const [topicQuery, setTopicQuery] = useState('')
  const [publicDataOnly, setPublicDataOnly] = useState(false)
  const [draft, setDraft] = useState<ProposalDraft>({
    question: '',
    why: '',
    dataRoute: '',
    area: content.programs[initialProgram].title,
    name: '',
    email: '',
  })
  const proposalRef = useRef<HTMLElement>(null)
  const proposalQuestionRef = useRef<HTMLTextAreaElement>(null)

  const activeProgramContent = content.programs[activeProgram]
  const activeDirections = directionsFor(activeProgramContent)
  const activeDirection =
    activeDirections.find((direction) => direction.id === activeDirectionId) ?? activeDirections[0]

  const questionsByTopic = useMemo(() => {
    const byTopic = new Map<string, typeof content.neuroimaging_starting_questions>()
    for (const question of content.neuroimaging_starting_questions) {
      const current = byTopic.get(question.topic) ?? []
      current.push(question)
      byTopic.set(question.topic, current)
    }
    return byTopic
  }, [])

  const filteredTopics = useMemo(() => {
    const query = topicQuery.trim().toLowerCase()
    return content.neuroimaging_topics.filter((topic) => {
      const matchesQuery =
        !query ||
        topic.name.toLowerCase().includes(query) ||
        topic.anchors.some((anchor) => anchor.title.toLowerCase().includes(query))
      return matchesQuery && (!publicDataOnly || topic.public_count > 0)
    })
  }, [publicDataOnly, topicQuery])

  const selectedTopic = filteredTopics.find((topic) => topic.id === selectedTopicId) ?? null
  const selectedQuestions = selectedTopic
    ? questionsByTopic.get(selectedTopic.id) ?? []
    : []

  const updateLocation = ({
    program,
    direction,
    topic,
  }: {
    program: ProgramId
    direction?: string
    topic?: string
  }) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('program', program)
    if (direction) params.set('direction', direction)
    else params.delete('direction')
    if (topic) params.set('topic', topic)
    else params.delete('topic')
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  const selectProgram = (nextProgram: string) => {
    if (!isProgramId(nextProgram)) return
    const nextDirections = directionsFor(content.programs[nextProgram])
    const nextDirection = nextDirections[0]?.id ?? ''
    setActiveProgram(nextProgram)
    setActiveDirectionId(nextDirection)
    setDraft((current) => ({ ...current, area: content.programs[nextProgram].title }))
    updateLocation({
      program: nextProgram,
      direction: nextDirection,
      topic: nextProgram === 'neuroimaging' ? selectedTopicId : undefined,
    })
  }

  const selectDirection = (directionId: string) => {
    setActiveDirectionId(directionId)
    updateLocation({
      program: activeProgram,
      direction: directionId,
      topic: activeProgram === 'neuroimaging' ? selectedTopicId : undefined,
    })
  }

  const selectTopic = (topic: NeuroimagingTopic) => {
    setSelectedTopicId(topic.id)
    updateLocation({
      program: 'neuroimaging',
      direction: activeDirection?.id,
      topic: topic.id,
    })
  }

  const useStartingQuestion = (question: string, programTitle: string) => {
    setDraft((current) => ({ ...current, question, area: programTitle }))
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    proposalRef.current?.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'start',
    })
    proposalQuestionRef.current?.focus()
  }

  return (
    <div className="min-w-0 bg-white text-gray-950">
      <section className="border-b border-gray-200 bg-gray-50">
        <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-14 sm:px-6 sm:py-16 lg:px-8 lg:py-20">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
              BR Autoresearch / Open call
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight text-gray-950 sm:text-5xl">
              Propose a question for BR to investigate.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-gray-700 sm:text-lg">
              Researchers share a starting point. The BR team refines the question with them,
              chooses a first exploration, and brings evidence back for review.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <a
                href="#proposal"
                className="inline-flex min-h-11 items-center justify-center rounded-md bg-gray-950 px-5 text-sm font-semibold text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
              >
                Submit a proposal
                <ArrowRight aria-hidden="true" className="ml-2 size-4" />
              </a>
              <a
                href="#landscape"
                className="inline-flex min-h-11 items-center justify-center rounded-md border border-gray-300 bg-white px-5 text-sm font-semibold text-gray-950 hover:border-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
              >
                Explore the landscape
              </a>
            </div>
            <p className="mt-6 max-w-2xl text-sm leading-6 text-gray-600">
              The first goal is to find a lead worth following. A promising result can later move
              into a separate validation study.
            </p>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-gray-600">
              {content.public_record.copy}{' '}
              <a
                href={content.public_record.href}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-gray-950 underline underline-offset-4 hover:text-gray-700"
              >
                {content.public_record.link_label}
                <span className="sr-only">, opens an external site</span>
              </a>
            </p>
          </div>
        </div>
      </section>

      <section id="landscape" className="scroll-mt-24 border-b border-gray-200" aria-labelledby="landscape-title">
        <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 sm:py-16 lg:px-8">
          <div className="grid gap-5 border-b border-gray-200 pb-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(18rem,0.65fr)] lg:gap-12">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Explore</p>
              <h2 id="landscape-title" className="mt-3 text-3xl font-semibold tracking-tight text-gray-950">
                Research landscape
              </h2>
            </div>
            <div className="space-y-3 text-sm leading-6 text-gray-700">
              <p>Browse directions, use an editable starting question, or bring a question that is not represented yet.</p>
              <p className="border-l-2 border-gray-300 pl-4 text-gray-600">
                Neuroimaging retains a 111-topic source index. This is a working landscape snapshot,
                not a real-time or complete review.
              </p>
            </div>
          </div>

          <Tabs value={activeProgram} onValueChange={selectProgram} className="mt-8">
            <TabsList
              aria-label="Research programs"
              className="flex h-auto w-full justify-start gap-1 overflow-x-auto rounded-none border-b border-gray-200 bg-transparent p-0"
            >
              {content.program_order.map((programId) => (
                <TabsTrigger
                  key={programId}
                  value={programId}
                  className="min-h-11 shrink-0 rounded-none border-b-2 border-transparent px-4 text-sm text-gray-600 shadow-none hover:text-gray-950 data-[state=active]:border-gray-950 data-[state=active]:bg-transparent data-[state=active]:text-gray-950 data-[state=active]:shadow-none"
                >
                  {content.programs[programId].short}
                </TabsTrigger>
              ))}
            </TabsList>

            {content.program_order.map((programId) => (
              <TabsContent key={programId} value={programId} className="mt-7">
                {programId === 'neuroimaging' ? (
                  <NeuroimagingLandscape
                    program={content.programs.neuroimaging}
                    directions={directionsFor(content.programs.neuroimaging)}
                    activeDirection={activeDirection}
                    onSelectDirection={selectDirection}
                    onUseAgendaQuestion={(question) => useStartingQuestion(question, content.programs.neuroimaging.title)}
                    topics={filteredTopics}
                    selectedTopic={selectedTopic}
                    selectedQuestions={selectedQuestions}
                    topicQuery={topicQuery}
                    publicDataOnly={publicDataOnly}
                    onTopicQueryChange={setTopicQuery}
                    onPublicDataOnlyChange={() => setPublicDataOnly((current) => !current)}
                    onSelectTopic={selectTopic}
                    onUseTopicQuestion={(question) => useStartingQuestion(question, content.programs.neuroimaging.title)}
                  />
                ) : (
                  <ProgramLandscape
                    program={content.programs[programId]}
                    directions={directionsFor(content.programs[programId])}
                    activeDirection={activeDirection}
                    onSelectDirection={selectDirection}
                    onUseQuestion={(question) => useStartingQuestion(question, content.programs[programId].title)}
                  />
                )}
              </TabsContent>
            ))}
          </Tabs>
        </div>
      </section>

      <section className="border-b border-gray-200 bg-gray-50" aria-labelledby="process-title">
        <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 sm:py-16 lg:px-8">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">How it works</p>
            <h2 id="process-title" className="mt-3 text-3xl font-semibold tracking-tight text-gray-950">
              From proposal to a useful next step
            </h2>
            <p className="mt-3 text-sm leading-6 text-gray-700">
              Proposing researchers stay involved as the question is revised and the first exploration is reviewed.
            </p>
          </div>
          <ol className="mt-8 grid divide-y divide-gray-200 border-y border-gray-200 sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-5">
            {processSteps.map(([number, title, body]) => (
              <li key={number} className="min-w-0 px-4 py-5 first:pl-0 sm:first:pl-0 lg:last:pr-0">
                <span className="font-mono text-xs text-gray-500">{number}</span>
                <h3 className="mt-3 text-sm font-semibold text-gray-950">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-gray-600">{body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="border-b border-gray-200" aria-labelledby="future-direction-title">
        <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 sm:py-16 lg:px-8">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
              {content.future_direction.eyebrow}
            </p>
            <h2 id="future-direction-title" className="mt-3 text-3xl font-semibold tracking-tight text-gray-950">
              {content.future_direction.title}
            </h2>
            <div className="mt-4 space-y-4 text-sm leading-6 text-gray-700">
              {content.future_direction.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section ref={proposalRef} id="proposal" className="scroll-mt-24" aria-labelledby="proposal-title">
        <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-14 sm:px-6 sm:py-16 lg:grid-cols-[minmax(0,0.75fr)_minmax(22rem,0.65fr)] lg:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Open call</p>
            <h2 id="proposal-title" className="mt-3 text-3xl font-semibold tracking-tight text-gray-950">
              Send the starting point.
            </h2>
            <p className="mt-4 max-w-xl text-sm leading-6 text-gray-700">
              A proposal can begin with a public dataset, data your team can access, an observation, or a scientific question. Selected proposals are refined with the proposing researchers before an episode begins.
            </p>
          </div>

          <form
            action={defaultProposalDestination}
            method="post"
            className="border border-gray-200 bg-gray-50 p-5 sm:p-6"
            aria-describedby="proposal-submission-status"
          >
            <input type="hidden" name="source" value="br-autoresearch-open-call" />
            <input type="hidden" name="_subject" value={content.proposal_submission.subject} />
            <input type="hidden" name="_template" value="table" />
            <input type="hidden" name="_next" value={formReturnUrl} />
            <input
              type="text"
              name="_honey"
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
              className="sr-only"
            />
            <div className="space-y-5">
              <FormField label="Scientific question" htmlFor="proposal-question">
                <textarea
                  ref={proposalQuestionRef}
                  id="proposal-question"
                  name="question"
                  required
                  value={draft.question}
                  onChange={(event) => setDraft((current) => ({ ...current, question: event.target.value }))}
                  placeholder="State the question, phenomenon, or observation in a few sentences."
                  className="min-h-32 w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm leading-6 text-gray-950 placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                />
              </FormField>
              <FormField label="Why is it worth investigating?" htmlFor="proposal-why">
                <textarea
                  id="proposal-why"
                  name="why"
                  value={draft.why}
                  onChange={(event) => setDraft((current) => ({ ...current, why: event.target.value }))}
                  placeholder="What would change if the answer were clearer?"
                  className="min-h-24 w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm leading-6 text-gray-950 placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                />
              </FormField>
              <FormField label="Data that may help" htmlFor="proposal-data-route">
                <input
                  id="proposal-data-route"
                  name="data_route"
                  value={draft.dataRoute}
                  onChange={(event) => setDraft((current) => ({ ...current, dataRoute: event.target.value }))}
                  placeholder="Public dataset, collaborator data, simulation, new experiment, or not yet known"
                  className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                />
              </FormField>
              <div className="grid gap-5 sm:grid-cols-2">
                <FormField label="Research area" htmlFor="proposal-area">
                  <select
                    id="proposal-area"
                    name="area"
                    value={draft.area}
                    onChange={(event) => setDraft((current) => ({ ...current, area: event.target.value }))}
                    className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                  >
                    {content.program_order.map((programId) => (
                      <option key={programId} value={content.programs[programId].title}>
                        {content.programs[programId].title}
                      </option>
                    ))}
                    <option value="Other or cross-cutting">Other or cross-cutting</option>
                  </select>
                </FormField>
                <FormField label="Name" htmlFor="proposal-name">
                  <input
                    id="proposal-name"
                    name="name"
                    required
                    value={draft.name}
                    onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                    autoComplete="name"
                    className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                  />
                </FormField>
              </div>
              <FormField label="Email" htmlFor="proposal-email">
                <input
                  id="proposal-email"
                  name="email"
                  type="email"
                  required
                  value={draft.email}
                  onChange={(event) => setDraft((current) => ({ ...current, email: event.target.value }))}
                  autoComplete="email"
                  className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                />
              </FormField>
            </div>

            <button
              type="submit"
              className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-md bg-gray-950 px-5 text-sm font-semibold text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
            >
              Submit proposal
            </button>
            <p
              id="proposal-submission-status"
              role="status"
              aria-live="polite"
              aria-atomic="true"
              className="mt-3 text-xs leading-5 text-gray-600"
            >
              {submissionStatus}
            </p>
          </form>
        </div>
      </section>

      <ResponsiveFooter maxWidth="desktop" className="flex flex-col justify-between gap-3 text-sm text-gray-600 sm:flex-row sm:items-center">
        <p>BR Autoresearch open call</p>
        <a
          href="#landscape"
          className="inline-flex min-h-11 items-center gap-1 font-medium text-gray-950 underline decoration-gray-400 underline-offset-4 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
        >
          Return to the landscape
          <ChevronRight aria-hidden="true" className="size-4" />
        </a>
      </ResponsiveFooter>
    </div>
  )
}

function ProgramLandscape({
  program,
  directions,
  activeDirection,
  onSelectDirection,
  onUseQuestion,
}: {
  program: ResearchProgram
  directions: AgendaDirection[]
  activeDirection?: AgendaDirection
  onSelectDirection: (directionId: string) => void
  onUseQuestion: (question: string) => void
}) {
  if (!activeDirection) return null

  return (
    <div>
      <ProgramSummary program={program} />
      <div className="mt-8 grid border-t border-gray-200 lg:grid-cols-[minmax(15rem,0.42fr)_minmax(0,1fr)]">
        <DirectionIndex
          directions={directions}
          activeDirectionId={activeDirection.id}
          onSelectDirection={onSelectDirection}
        />
        <AgendaDirectionDetail
          direction={activeDirection}
          programTitle={program.title}
          onUseQuestion={onUseQuestion}
        />
      </div>
    </div>
  )
}

function NeuroimagingLandscape({
  program,
  directions,
  activeDirection,
  onSelectDirection,
  onUseAgendaQuestion,
  topics,
  selectedTopic,
  selectedQuestions,
  topicQuery,
  publicDataOnly,
  onTopicQueryChange,
  onPublicDataOnlyChange,
  onSelectTopic,
  onUseTopicQuestion,
}: {
  program: ResearchProgram
  directions: AgendaDirection[]
  activeDirection?: AgendaDirection
  onSelectDirection: (directionId: string) => void
  onUseAgendaQuestion: (question: string) => void
  topics: NeuroimagingTopic[]
  selectedTopic: NeuroimagingTopic | null
  selectedQuestions: typeof content.neuroimaging_starting_questions
  topicQuery: string
  publicDataOnly: boolean
  onTopicQueryChange: (query: string) => void
  onPublicDataOnlyChange: () => void
  onSelectTopic: (topic: NeuroimagingTopic) => void
  onUseTopicQuestion: (question: string) => void
}) {
  return (
    <div>
      <ProgramSummary program={program} />
      {activeDirection ? (
        <section className="mt-8" aria-labelledby="agenda-title">
          <div className="border-b border-gray-200 pb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Field agenda</p>
            <h3 id="agenda-title" className="mt-2 text-2xl font-semibold tracking-tight text-gray-950">
              Twelve directions framing the source index
            </h3>
          </div>
          <div className="mt-5 grid border-t border-gray-200 lg:grid-cols-[minmax(15rem,0.42fr)_minmax(0,1fr)]">
            <DirectionIndex
              directions={directions}
              activeDirectionId={activeDirection.id}
              onSelectDirection={onSelectDirection}
            />
            <AgendaDirectionDetail
              direction={activeDirection}
              programTitle={program.title}
              onUseQuestion={onUseAgendaQuestion}
            />
          </div>
        </section>
      ) : null}

      <section className="mt-12" aria-labelledby="topic-index-title">
        <div className="grid gap-4 border-b border-gray-200 pb-5 lg:grid-cols-[minmax(0,0.7fr)_minmax(16rem,0.5fr)] lg:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Source index</p>
            <h3 id="topic-index-title" className="mt-2 text-2xl font-semibold tracking-tight text-gray-950">
              111 neuroimaging topics
            </h3>
          </div>
          <p className="text-sm leading-6 text-gray-600">
            Each topic includes selected anchors and an editable starting question.
          </p>
        </div>

        <div className="mt-6 grid border-y border-gray-200 lg:grid-cols-[minmax(15rem,0.42fr)_minmax(0,1fr)]">
          <aside className="border-b border-gray-200 bg-gray-50 p-4 lg:border-b-0 lg:border-r">
            <label htmlFor="neuroimaging-topic-search" className="text-sm font-semibold text-gray-950">
              Search the source index
            </label>
            <div className="relative mt-3">
              <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-gray-500" />
              <input
                id="neuroimaging-topic-search"
                type="search"
                value={topicQuery}
                onChange={(event) => onTopicQueryChange(event.target.value)}
                placeholder="Search topics or anchors"
                className="min-h-11 w-full rounded-md border border-gray-300 bg-white py-2 pl-10 pr-3 text-sm text-gray-950 placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
              />
            </div>
            <button
              type="button"
              aria-pressed={publicDataOnly}
              onClick={onPublicDataOnlyChange}
              className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-gray-700 underline decoration-gray-400 underline-offset-4 hover:text-gray-950 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
            >
              Public data only
            </button>
            <p className="mt-4 text-xs leading-5 text-gray-500">
              {topics.length} matching {topics.length === 1 ? 'topic' : 'topics'}
            </p>
            <div className="mt-3 lg:hidden">
              <label htmlFor="neuroimaging-topic-select" className="sr-only">
                Choose a neuroimaging topic
              </label>
              <select
                id="neuroimaging-topic-select"
                value={selectedTopic?.id ?? ''}
                onChange={(event) => {
                  const topic = topics.find((candidate) => candidate.id === event.target.value)
                  if (topic) onSelectTopic(topic)
                }}
                disabled={topics.length === 0}
                className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-gray-100"
              >
                {!selectedTopic ? (
                  <option value="">
                    {topics.length === 0 ? 'No matching topics' : 'Choose a matching topic'}
                  </option>
                ) : null}
                {topics.map((topic) => (
                  <option key={topic.id} value={topic.id}>
                    {topic.name}{topic.public_count > 0 ? ' (Public data)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div
              aria-label="Neuroimaging topics"
              className="mt-3 hidden divide-y divide-gray-200 border-y border-gray-200 lg:block lg:max-h-[34rem] lg:overflow-y-auto"
            >
              {topics.map((topic) => {
                const selected = topic.id === selectedTopic?.id
                return (
                  <button
                    key={topic.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelectTopic(topic)}
                    className={`flex min-h-11 w-full items-center justify-between gap-3 px-3 py-3 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gray-900 ${
                      selected ? 'bg-white font-semibold text-gray-950' : 'text-gray-700 hover:bg-white'
                    }`}
                  >
                    <span className="min-w-0">{topic.name}</span>
                    {topic.public_count > 0 ? (
                      <span className="shrink-0 text-xs font-medium text-gray-500">Public data</span>
                    ) : null}
                  </button>
                )
              })}
              {topics.length === 0 ? (
                <p className="px-3 py-5 text-sm leading-6 text-gray-600">No topics match this search.</p>
              ) : null}
            </div>
          </aside>

          <div className="min-w-0 bg-white px-5 py-6 sm:px-7">
            {selectedTopic ? (
              <TopicDetail
                topic={selectedTopic}
                questions={selectedQuestions}
                onUseQuestion={onUseTopicQuestion}
              />
            ) : (
              <p className="text-sm leading-6 text-gray-600">Search for a topic to view its source context.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function ProgramSummary({ program }: { program: ResearchProgram }) {
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(15rem,0.7fr)_minmax(0,1fr)]">
      <div>
        <h3 className="text-2xl font-semibold tracking-tight text-gray-950">{program.title}</h3>
        <ol className="mt-5 grid gap-3 border-y border-gray-200 py-4 sm:grid-cols-3">
          {program.big_questions.map((question, index) => (
            <li key={question} className="text-sm leading-6 text-gray-700">
              <span className="mr-2 font-mono text-xs text-gray-500">{String(index + 1).padStart(2, '0')}</span>
              {question}
            </li>
          ))}
        </ol>
      </div>
      <p className="text-sm leading-6 text-gray-700">{program.copy}</p>
    </div>
  )
}

function DirectionIndex({
  directions,
  activeDirectionId,
  onSelectDirection,
}: {
  directions: AgendaDirection[]
  activeDirectionId: string
  onSelectDirection: (directionId: string) => void
}) {
  return (
    <aside className="bg-gray-50 p-4 lg:border-r lg:border-gray-200" aria-label="Research directions">
      <p className="px-3 pb-3 text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
        Research directions
      </p>
      <div className="lg:hidden">
        <label htmlFor="research-direction-select" className="sr-only">
          Choose a research direction
        </label>
        <select
          id="research-direction-select"
          value={activeDirectionId}
          onChange={(event) => onSelectDirection(event.target.value)}
          className="min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
        >
          {directions.map((direction) => (
            <option key={direction.id} value={direction.id}>
              {direction.title}
            </option>
          ))}
        </select>
      </div>
      <div className="hidden divide-y divide-gray-200 border-y border-gray-200 lg:block lg:max-h-[38rem] lg:overflow-y-auto">
        {directions.map((direction, index) => {
          const selected = direction.id === activeDirectionId
          return (
            <button
              key={direction.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelectDirection(direction.id)}
              className={`grid min-h-11 w-full grid-cols-[2rem_minmax(0,1fr)] gap-2 px-3 py-3 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gray-900 ${
                selected ? 'bg-white font-semibold text-gray-950' : 'text-gray-700 hover:bg-white'
              }`}
            >
              <span className="font-mono text-xs text-gray-500">{String(index + 1).padStart(2, '0')}</span>
              <span>{direction.title}</span>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

function TopicDetail({
  topic,
  questions,
  onUseQuestion,
}: {
  topic: NeuroimagingTopic
  questions: typeof content.neuroimaging_starting_questions
  onUseQuestion: (question: string) => void
}) {
  const headingId = `topic-${encodeURIComponent(topic.id)}`

  return (
    <section aria-labelledby={headingId}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Neuroimaging source direction</p>
      <h4 id={headingId} className="mt-2 text-2xl font-semibold tracking-tight text-gray-950">
        {topic.name}
      </h4>
      <div className="mt-5 border-y border-gray-200 py-4">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Selected anchors</p>
        <ul className="mt-3 space-y-3">
          {topic.anchors.map((anchor) => (
            <li key={`${topic.id}-${anchor.url}`}>
              <a
                href={anchor.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-11 items-start gap-1 text-sm font-medium leading-6 text-gray-950 underline decoration-gray-400 underline-offset-4 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
              >
                <span className="min-w-0">
                  <span className="block">{anchor.title}</span>
                  <span className="mt-1 block text-xs font-normal text-gray-500">
                    {anchor.citation}
                  </span>
                  <span className="sr-only">, opens an external site</span>
                </span>
                <ArrowRight aria-hidden="true" className="mt-1.5 size-3.5 shrink-0" />
              </a>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-2">
        {questions.map((question) => (
          <StartingQuestion
            key={`${question.topic}:${question.id}`}
            topicId={topic.id}
            question={question}
            onUseQuestion={onUseQuestion}
          />
        ))}
      </div>
    </section>
  )
}

function FormField({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-2 block text-sm font-semibold text-gray-950">
        {label}
      </label>
      {children}
    </div>
  )
}

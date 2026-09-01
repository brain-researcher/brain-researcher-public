'use client'

import { useState } from 'react'
import { ArrowUpRight, ChevronDown } from 'lucide-react'

import type { NeuroimagingStartingQuestion } from '@/content/autoresearch'

interface StartingQuestionProps {
  question: NeuroimagingStartingQuestion
  topicId: string
  onUseQuestion: (question: string) => void
}

export function StartingQuestion({ question, topicId, onUseQuestion }: StartingQuestionProps) {
  const [sourceOpen, setSourceOpen] = useState(false)
  const disclosureId = `source-${encodeURIComponent(topicId)}-${encodeURIComponent(question.id)}`

  return (
    <article className="border-t border-gray-200 py-5 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-600">
          {question.data_label}
        </span>
      </div>
      <h5 className="mt-4 text-lg font-semibold leading-7 tracking-tight text-gray-950">
        {question.question}
      </h5>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          aria-expanded={sourceOpen}
          aria-controls={disclosureId}
          onClick={() => setSourceOpen((open) => !open)}
          className="inline-flex min-h-11 items-center gap-2 self-start text-sm font-medium text-gray-700 underline decoration-gray-400 underline-offset-4 hover:text-gray-950 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
        >
          See source
          <ChevronDown
            aria-hidden="true"
            className={`size-4 transition-transform motion-reduce:transition-none ${sourceOpen ? 'rotate-180' : ''}`}
          />
        </button>
        <button
          type="button"
          onClick={() => onUseQuestion(question.question)}
          className="inline-flex min-h-11 items-center justify-center rounded-md bg-gray-950 px-4 text-sm font-semibold text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
          aria-label={`Use starting question: ${question.question}`}
        >
          Use as a starting point
        </button>
      </div>

      {sourceOpen ? (
        <div id={disclosureId} className="mt-4 border-l-2 border-gray-300 bg-gray-50 px-4 py-4 text-sm text-gray-700">
          <dl className="space-y-4">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Source paper</dt>
              <dd className="mt-1 leading-6">
                <a
                  href={question.paper_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-start gap-1 font-medium text-gray-950 underline decoration-gray-400 underline-offset-4 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
                >
                  <span>
                    {question.paper_title} ({question.citation})
                    <span className="sr-only">, opens an external site</span>
                  </span>
                  <ArrowUpRight aria-hidden="true" className="mt-1 size-3.5 shrink-0" />
                </a>
              </dd>
            </div>
            {question.source_question ? (
              <div>
                <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Original source lead</dt>
                <dd className="mt-1 leading-6">{question.source_question}</dd>
              </div>
            ) : null}
            {question.why ? (
              <div>
                <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Editorial note</dt>
                <dd className="mt-1 leading-6">{question.why}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}
    </article>
  )
}

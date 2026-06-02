'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Brain, Check, RotateCcw } from 'lucide-react'

// Shared question a researcher would actually ask — concrete constraints, real deliverable.
const PROMPT =
  'Find a public resting-state fMRI dataset with ≥40 subjects, measure within-DMN connectivity with the Schaefer-400 atlas (Yeo-7), preprocessed with fMRIPrep + Nilearn. Give me a reproducible recipe I can submit to SLURM.'

// Left: a plain LLM with no grounding (correct method knowledge, but can't ground the dataset/run).
const LEFT_TEXT = `For within-DMN connectivity you'd preprocess with fMRIPrep, then use Nilearn with the Schaefer-400 atlas restricted to the Yeo-7 default-mode parcels.

I can't query dataset catalogs or check subject counts, so I can't confirm one actually has ≥40 subjects. You'd verify that on OpenNeuro yourself.

And I can't write a SLURM script bound to a real dataset path. General shape: fMRIPrep → extract time-series → correlate → Fisher-z.`

// Right: same agent, with Brain Researcher over MCP (grounded + runnable).
const RIGHT_TOOLS = ['kg_search_datasets', 'workflow_search', 'get_execution_recipe', 'plan_preflight']
const RIGHT_TEXT = `Catalog match: ds000030 (UCLA CNP), resting-state, BIDS-valid, 250+ subjects. Meets ≥40.

Pipeline: rest_connectome_e2e on fMRIPrep + Nilearn, Schaefer-400 masked to Yeo-7 DMN, Fisher-z. Validated · ~25 min/subject on SLURM.

  br run rest-connectome --dataset ds000030 --atlas schaefer400 --network DMN --target slurm

Preflight passed: BIDS valid, atlas + paths resolved. Artifacts: per-subject + group DMN matrices, report, provenance manifest. Submit to your cluster, or open in Studio?`

// --- timeline (ms) ---
const PROMPT_CPS = 50
const ANS_CPS = 95
const PROMPT_START = 350
const PROMPT_DUR = (PROMPT.length / PROMPT_CPS) * 1000
const ANSWERS_START = PROMPT_START + PROMPT_DUR + 450
const LEFT_DUR = (LEFT_TEXT.length / ANS_CPS) * 1000
const CHIP_STEP = 380
const CHIPS_DUR = RIGHT_TOOLS.length * CHIP_STEP + 200
const RIGHT_TEXT_START = ANSWERS_START + CHIPS_DUR
const RIGHT_DUR = (RIGHT_TEXT.length / ANS_CPS) * 1000
const END = Math.max(ANSWERS_START + LEFT_DUR, RIGHT_TEXT_START + RIGHT_DUR) + 500

function sliceByRate(text: string, elapsed: number, cps: number) {
  if (elapsed <= 0) return ''
  const chars = Math.floor((elapsed / 1000) * cps)
  return chars >= text.length ? text : text.slice(0, chars)
}

function Cursor({ show }: { show: boolean }) {
  if (!show) return null
  return <span className="ml-0.5 inline-block w-[2px] animate-pulse bg-slate-400 align-middle" style={{ height: '1em' }} />
}

export function AgentComparisonDemo() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef(0)
  const hasPlayedRef = useRef(false)
  const [playhead, setPlayhead] = useState(0)
  const [phase, setPhase] = useState<'idle' | 'playing' | 'done'>('idle')

  const play = useCallback(() => {
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setPlayhead(END)
      setPhase('done')
      return
    }
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    startRef.current = performance.now()
    setPhase('playing')
    const loop = (now: number) => {
      const p = now - startRef.current
      if (p >= END) {
        setPlayhead(END)
        setPhase('done')
        return
      }
      setPlayhead(p)
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
  }, [])

  // Auto-play once when scrolled into view.
  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !hasPlayedRef.current) {
            hasPlayedRef.current = true
            play()
          }
        }
      },
      { threshold: 0.4 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [play])

  useEffect(() => () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
  }, [])

  const promptShown = sliceByRate(PROMPT, playhead - PROMPT_START, PROMPT_CPS)
  const promptTyping = playhead > PROMPT_START && playhead < PROMPT_START + PROMPT_DUR
  const answersBegun = playhead >= ANSWERS_START

  const leftShown = sliceByRate(LEFT_TEXT, playhead - ANSWERS_START, ANS_CPS)
  const leftTyping = answersBegun && playhead < ANSWERS_START + LEFT_DUR

  const chipsRevealed = answersBegun
    ? Math.min(RIGHT_TOOLS.length, Math.floor((playhead - ANSWERS_START) / CHIP_STEP) + 1)
    : 0
  const rightShown = sliceByRate(RIGHT_TEXT, playhead - RIGHT_TEXT_START, ANS_CPS)
  const rightTyping = playhead > RIGHT_TEXT_START && playhead < RIGHT_TEXT_START + RIGHT_DUR

  return (
    <div ref={containerRef} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      {/* window chrome + prompt */}
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <div className="mb-2 flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="ml-2 text-xs font-medium text-slate-400">your coding agent</span>
        </div>
        <div className="flex items-start gap-2 text-sm">
          <span className="select-none pt-0.5 font-mono text-slate-400">›</span>
          <p className="font-mono text-slate-800">
            {promptShown}
            <Cursor show={promptTyping} />
          </p>
        </div>
      </div>

      {/* two-up comparison */}
      <div className="grid divide-y divide-slate-200 md:grid-cols-2 md:divide-x md:divide-y-0">
        {/* Left — Claude alone */}
        <div className="flex min-h-[300px] flex-col p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-semibold text-slate-900">Claude</span>
            <span className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-400">
              no tools
            </span>
          </div>
          <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-600">
            {leftShown}
            <Cursor show={leftTyping} />
          </div>
        </div>

        {/* Right — Claude + Brain Researcher */}
        <div className="flex min-h-[300px] flex-col bg-slate-50/50 p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <Brain className="h-4 w-4" />
              Claude + Brain Researcher
            </span>
            <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-medium text-white">MCP</span>
          </div>

          {/* tool calls */}
          <div className="mb-3 flex flex-wrap gap-1.5">
            {RIGHT_TOOLS.slice(0, chipsRevealed).map((tool) => (
              <span
                key={tool}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
              >
                <Check className="h-3 w-3 text-emerald-600" />
                {tool}
              </span>
            ))}
          </div>

          <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
            {rightShown}
            <Cursor show={rightTyping} />
          </div>
        </div>
      </div>

      {/* footer / replay */}
      <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-4 py-2">
        <span className="text-[11px] text-slate-400">
          {phase === 'done' ? 'Same question. Same agent. One of them can run it.' : 'Streaming demo…'}
        </span>
        <button
          type="button"
          onClick={play}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900"
        >
          <RotateCcw className="h-3 w-3" />
          Replay
        </button>
      </div>
    </div>
  )
}

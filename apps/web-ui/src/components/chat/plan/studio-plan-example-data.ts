export type StudioPlanProjectionRow = {
  id: string
  label: string
  value: string
  detail?: string
  status?: 'passed' | 'warning' | 'blocked' | 'info'
}

export type StudioPlanProjectionAlert = {
  id: string
  label: string
  severity: 'warning' | 'blocked'
  message: string
}

export type StudioNotebookStep = {
  id: string
  title: string
  detail: string
  status: 'done' | 'running' | 'queued'
}

export type StudioNotebookArtifact = {
  id: string
  shortLabel: string
  title: string
  kind: 'chart' | 'table' | 'report'
  summary: string
  insights: string[]
  previewBars?: Array<{ label: string; value: number }>
  previewRows?: Array<{ label: string; value: string; meta: string }>
  previewLines?: string[]
}

export type StudioNotebookExampleData = {
  userPrompt: string
  agentPlan: {
    summary: string
    bullets: string[]
  }
  checkpoint: {
    status: 'ready' | 'warning' | 'blocked' | 'running'
    intentTitle: string
    intentSummary: string
    summaryRows: StudioPlanProjectionRow[]
    alerts: StudioPlanProjectionAlert[]
    runtime: string
    primaryLabel: string
    secondaryLabel: string
    canRun: boolean
  }
  steps: StudioNotebookStep[]
  resultsSummary: string
  artifacts: StudioNotebookArtifact[]
  defaultArtifactId: string
  followupHint: string
}

export const DEFAULT_STUDIO_PLAN_EXAMPLE: StudioNotebookExampleData = {
  userPrompt:
    'Run resting-state connectivity on ds000114, use a Schaefer atlas, summarize the strongest network effects, and show me the QC artifacts inline.',
  agentPlan: {
    summary:
      'I found a mounted BIDS dataset, selected a rest-connectome workflow, and prepared a five-step run with QC artifacts and a compact report.',
    bullets: [
      'Resolve dataset mount and version from the current thread context.',
      'Pick a workflow that can emit both connectivity outputs and QC previews.',
      'Prepare a runnable checkpoint instead of asking the user to fill a side form.',
      'Keep edits in chat so the next turn can mutate the same plan and rerun.',
    ],
  },
  checkpoint: {
    status: 'blocked',
    intentTitle: 'Plan checkpoint',
    intentSummary:
      'This cell is the approval surface. The user reviews what the agent prepared, not a separate planner UI.',
    summaryRows: [
      {
        id: 'dataset',
        label: 'Dataset',
        value: 'ds000114 · v1.0.1',
        detail: 'BIDS · 20 subjects · mounted',
        status: 'passed',
      },
      {
        id: 'workflow',
        label: 'Workflow',
        value: 'Rest connectome',
        detail: 'Schaefer-400 · correlation · ICA-AROMA',
        status: 'passed',
      },
      {
        id: 'execution-shape',
        label: 'Execution shape',
        value: '5 notebook steps prepared',
        detail: 'Preprocess → extract timeseries → compute connectome → QC → summarize artifacts',
        status: 'info',
      },
    ],
    alerts: [
      {
        id: 'task-choice',
        label: 'Missing workflow task selection',
        severity: 'blocked',
        message: 'The agent still needs a final rest-task interpretation before the run can start.',
      },
      {
        id: 'verification',
        label: 'Verification is partial',
        severity: 'warning',
        message: 'Mount access was confirmed from cached source metadata rather than a fresh probe.',
      },
    ],
    runtime: '~18 min',
    primaryLabel: 'Run',
    secondaryLabel: 'Ask agent',
    canRun: false,
  },
  steps: [
    {
      id: 'step-1',
      title: 'Dataset mount resolved',
      detail: 'Agent matched the prompt to ds000114 and found a mounted BIDS layout with 20 subjects.',
      status: 'done',
    },
    {
      id: 'step-2',
      title: 'Workflow mapped from intent',
      detail: 'Rest-connectome pipeline selected with Schaefer atlas and correlation edges.',
      status: 'done',
    },
    {
      id: 'step-3',
      title: 'Run checkpoint waiting on one missing input',
      detail: 'The notebook is paused until the chat thread or advanced editor resolves the missing task.',
      status: 'running',
    },
    {
      id: 'step-4',
      title: 'Artifact viewer ready',
      detail: 'QC plot, regional summary table, and run report are prewired into the right inspector.',
      status: 'queued',
    },
  ],
  resultsSummary:
    'Artifacts appear inline as soon as they are emitted. Selecting one pins it in the right inspector instead of changing tabs.',
  artifacts: [
    {
      id: 'qc-plot',
      shortLabel: 'QC plot',
      title: 'Motion QC overview',
      kind: 'chart',
      summary: 'Framewise displacement stays low for most subjects, with one moderate outlier.',
      insights: [
        'Median FD stays below 0.2 mm for the first three quartiles.',
        'One subject crosses the review threshold and would be surfaced back in chat.',
        'This card is just a focused preview; the result still belongs to the notebook stream.',
      ],
      previewBars: [
        { label: 'Q1', value: 0.24 },
        { label: 'Q2', value: 0.32 },
        { label: 'Q3', value: 0.41 },
        { label: 'Q4', value: 0.68 },
      ],
    },
    {
      id: 'region-table',
      shortLabel: 'Region table',
      title: 'Top network effects',
      kind: 'table',
      summary: 'The strongest effects localize to DMN-salience and frontoparietal interactions.',
      insights: [
        'Posterior cingulate to insula coupling is the highest-ranked effect.',
        'The table would stay selectable from both the notebook cell and the inspector rail.',
      ],
      previewRows: [
        { label: 'PCC → Insula', value: '0.41', meta: 'q=0.008' },
        { label: 'mPFC → IPL', value: '0.37', meta: 'q=0.013' },
        { label: 'dlPFC → Precuneus', value: '0.31', meta: 'q=0.021' },
      ],
    },
    {
      id: 'run-report',
      shortLabel: 'Run report',
      title: 'Narrative run report',
      kind: 'report',
      summary: 'A compact prose summary of the prepared run, blockers, and expected deliverables.',
      insights: [
        'This gives the user a readable summary without opening a separate plan form.',
        'Follow-up edits would regenerate this report alongside the plan checkpoint.',
      ],
      previewLines: [
        '> Rest-connectome notebook is ready except for one missing task choice.',
        '> Expected deliverables: QC plot, connectome matrix, ranked effect table, narrative summary.',
        '> Next best action: ask the agent to resolve the task ambiguity in chat, then rerun.',
      ],
    },
  ],
  defaultArtifactId: 'qc-plot',
  followupHint:
    'Follow-up edits should happen here in chat. The agent updates the notebook and refreshes the checkpoint cell.',
}

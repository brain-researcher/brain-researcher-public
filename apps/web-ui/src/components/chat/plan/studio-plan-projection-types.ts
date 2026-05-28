export type StudioPlanProjectionStatus = 'ready' | 'warning' | 'blocked' | 'running'

export type StudioPlanProjectionRow = {
  id: string
  label: string
  value: string
  detail?: string
  status?: 'passed' | 'warning' | 'blocked' | 'info'
}

export type StudioPlanProjectionAlert = {
  id: string
  severity: 'warning' | 'blocked'
  label: string
  message: string
}

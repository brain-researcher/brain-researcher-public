export function isTruthyQueryValue(raw: string | null | undefined): boolean {
  if (typeof raw !== 'string') return false
  const normalized = raw.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

export function buildStudioPlanHref(nextParams: URLSearchParams): string {
  const params = new URLSearchParams(nextParams.toString())
  params.set('tab', 'plan')
  params.delete('onboarding')
  params.delete('pickDataset')
  params.delete('pick_dataset')
  const suffix = params.toString()
  return suffix ? `/studio?${suffix}` : '/studio?tab=plan'
}

export function buildDatasetsPickerHref(returnTo: string): string {
  return `/datasets?pick=1&returnTo=${encodeURIComponent(returnTo)}`
}

export function buildStudioDatasetsPickerHref(nextParams: URLSearchParams): string {
  return buildDatasetsPickerHref(buildStudioPlanHref(nextParams))
}

import { redirect } from "next/navigation"

type SearchParams = Record<string, string | string[] | undefined>

const JOB_PREFIXES = ["job_", "run_", "builder_", "pipeline_"]

function toSearchParams(searchParams: SearchParams) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(searchParams)) {
    if (value === undefined) continue
    if (Array.isArray(value)) {
      value.forEach((entry) => search.append(key, entry))
    } else {
      search.set(key, value)
    }
  }
  return search
}

function isJobIdentifier(value: string) {
  return JOB_PREFIXES.some((prefix) => value.toLowerCase().startsWith(prefix))
}

export default function RunRedirect({
  params,
  searchParams,
}: {
  params: { demoId: string }
  searchParams: SearchParams
}) {
  const { demoId } = params

  if (isJobIdentifier(demoId)) {
    const rawQuery = toSearchParams(searchParams).toString()
    const suffix = rawQuery ? `?${rawQuery}` : ""
    redirect(`/analyses/${demoId}${suffix}`)
  }

  redirect('/studio')
}

export const dynamic = "force-dynamic"

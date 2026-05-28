import { redirect } from 'next/navigation'

type ToolsRedirectPageProps = {
  searchParams?: Record<string, string | string[] | undefined>
}

export default function ToolsRedirectPage({ searchParams }: ToolsRedirectPageProps) {
  const params = new URLSearchParams()

  for (const [key, value] of Object.entries(searchParams ?? {})) {
    if (value == null) continue
    if (Array.isArray(value)) {
      value.forEach((entry) => params.append(key, entry))
    } else {
      params.set(key, value)
    }
  }

  const suffix = params.toString()
  redirect(suffix ? `/library/tools?${suffix}` : '/library/tools')
}

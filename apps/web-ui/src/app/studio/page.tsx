import { redirect } from 'next/navigation'

interface StudioPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

export default async function StudioPage({ searchParams }: StudioPageProps) {
  const params = await searchParams
  const nextParams = new URLSearchParams()

  for (const [key, value] of Object.entries(params ?? {})) {
    if (value == null) continue
    if (Array.isArray(value)) {
      value.forEach((entry) => nextParams.append(key, entry))
    } else {
      nextParams.set(key, value)
    }
  }

  const suffix = nextParams.toString()
  redirect(suffix ? `/hub?${suffix}` : '/hub')
}

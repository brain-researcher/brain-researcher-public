export const dynamic = 'force-dynamic'

export async function GET() {
  const payload = {
    status: 'ok',
    service: 'web_ui',
    timestamp: new Date().toISOString(),
    build_git_sha:
      process.env.NEXT_PUBLIC_BUILD_GIT_SHA ||
      process.env.VERCEL_GIT_COMMIT_SHA ||
      process.env.GIT_SHA ||
      null,
  }

  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}


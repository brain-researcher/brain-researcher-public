import fs from 'node:fs'
import path from 'node:path'

const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const nextDir = path.join(rootDir, '.next')
const serverAppDir = path.join(nextDir, 'server', 'app')
const requiredClientChunks = [
  path.join(nextDir, 'static', 'chunks', 'main-app.js'),
  path.join(nextDir, 'static', 'chunks', 'app-pages-internals.js'),
]

if (process.env.SKIP_NEXT_DEV_CACHE_REPAIR === '1') {
  process.exit(0)
}

if (!fs.existsSync(nextDir)) {
  process.exit(0)
}

const hasServerAppArtifacts = fs.existsSync(serverAppDir)
const missingRequiredChunk = requiredClientChunks.find((chunkPath) => !fs.existsSync(chunkPath))

if (hasServerAppArtifacts && missingRequiredChunk) {
  fs.rmSync(nextDir, { recursive: true, force: true })
  console.log(
    `[repair-next-dev-cache] Removed stale .next cache because required app-router chunk was missing: ${path.relative(
      rootDir,
      missingRequiredChunk,
    )}`,
  )
}

import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const appRoot = path.resolve(__dirname, '..')
const sourceDir = path.join(appRoot, 'node_modules', 'monaco-editor', 'min', 'vs')
const targetDir = path.join(appRoot, 'public', 'monaco', 'vs')

if (!existsSync(sourceDir)) {
  console.error(`Monaco assets not found at ${sourceDir}`)
  process.exit(1)
}

mkdirSync(path.dirname(targetDir), { recursive: true })
rmSync(targetDir, { recursive: true, force: true })
cpSync(sourceDir, targetDir, { recursive: true })

console.log(`Synced Monaco assets to ${targetDir}`)

#!/usr/bin/env node

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

function ensureDir(dirPath) {
  try {
    fs.mkdirSync(dirPath, { recursive: true })
  } catch (error) {
    console.error(`Failed to create temp dir: ${dirPath}`)
    console.error(error)
    process.exit(1)
  }
}

function resolveTmpDir() {
  const configured =
    process.env.BR_TMPDIR ||
    process.env.PW_TMPDIR ||
    process.env.TMPDIR ||
    process.env.TEMP ||
    process.env.TMP

  if (configured && configured.trim()) return configured.trim()

  // This repo runs in environments where /tmp may not be writable; keep a project-local fallback.
  return path.resolve(process.cwd(), '.tmp')
}

const tmpDir = resolveTmpDir()
ensureDir(tmpDir)

process.env.TMPDIR = tmpDir
process.env.TEMP = tmpDir
process.env.TMP = tmpDir

const args = process.argv.slice(2)
const npxBin = process.platform === 'win32' ? 'npx.cmd' : 'npx'

const child = spawn(npxBin, ['playwright', ...args], {
  stdio: 'inherit',
  env: process.env,
})

child.on('exit', (code) => process.exit(code ?? 1))

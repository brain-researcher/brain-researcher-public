// vite.config.mjs
import { defineConfig } from 'vite'
import { execSync } from 'node:child_process'
import { resolve } from 'node:path'
import { rmSync, cpSync, existsSync, mkdirSync } from 'node:fs'

export default defineConfig({
  build: { outDir: 'dist', emptyOutDir: true },
  plugins: [
    {
      name: 'next-static-export-adapter',
      apply: 'build',
      buildStart() {
        // 1) Run Next static build (next.config.js already has output:'export')
        console.log('[adapter] running: npm run build (next build)')
        execSync('npm run build', { stdio: 'inherit' })
      },
      closeBundle() {
        // 2) Copy ./out -> ./dist for Vite publisher to deploy
        const from = resolve(process.cwd(), 'out')
        const to = resolve(process.cwd(), 'dist')
        if (!existsSync(from)) throw new Error('[adapter] Next build did not produce ./out')
        rmSync(to, { recursive: true, force: true })
        mkdirSync(to, { recursive: true })
        cpSync(from, to, { recursive: true })
        console.log('[adapter] copied ./out -> ./dist')
      },
    },
  ],
})
import fs from 'fs'
import path from 'path'
import yaml from 'js-yaml'

type BehaviorPolicy = Record<string, unknown>

const findConfigsDir = (): string | null => {
  let current = process.cwd()
  for (let i = 0; i < 6; i += 1) {
    const candidate = path.join(current, 'configs')
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      return candidate
    }
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  return null
}

const loadYamlPolicies = (configsDir: string): BehaviorPolicy[] => {
  const entries = fs.readdirSync(configsDir, { withFileTypes: true })
  const files = entries
    .filter((entry) => entry.isFile() && /^behavior.*\.ya?ml$/i.test(entry.name))
    .map((entry) => path.join(configsDir, entry.name))

  const policies: BehaviorPolicy[] = []
  for (const file of files) {
    try {
      const content = fs.readFileSync(file, 'utf8')
      const parsed = yaml.load(content)
      if (parsed && typeof parsed === 'object') {
        policies.push(parsed as BehaviorPolicy)
      }
    } catch {
      // Skip unreadable or malformed files
    }
  }
  return policies
}

export async function load_behavior_policies() {
  const configsDir = findConfigsDir()
  if (!configsDir) return []
  return loadYamlPolicies(configsDir)
}

'use client'

import Link from 'next/link'
import { Copy, ExternalLink } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { MCP_TOKEN_PLACEHOLDER } from '@/lib/mcp-config-snippets'

const STARTER_REPO_URL = 'https://github.com/zjc062/brain_researcher'

const TERMINAL_SETUP = [
  'nano ~/.zshrc',
  '',
  '# Brain Researcher MCP',
  `export BR_MCP_TOKEN="${MCP_TOKEN_PLACEHOLDER}"`,
  'export BR_MCP_AUTH_HEADER="Bearer ${BR_MCP_TOKEN}"',
  '',
  'source ~/.zshrc',
  'test -n "$BR_MCP_TOKEN" && echo "BR_MCP_TOKEN is set"',
].join('\n')

const SMOKE_PROMPT_CODEX =
  'show me the status of brain_researcher_mcp. Use the Brain Researcher MCP server_info and system_self_test tools. Keep the answer concise.'

const SMOKE_PROMPT_CLAUDE =
  'show me the status of brain_researcher_mcp. Use the brain-researcher MCP server_info and system_self_test tools. Keep the answer concise.'

const HANDOFF_PROMPT = [
  'Use Brain Researcher MCP to prepare a runnable recipe for resting-state connectivity on ds000114.',
  'First inspect the available MCP tools, then call server_info and system_self_test.',
  'Use workflow_search for resting-state connectivity and then get_execution_recipe with tool_id="workflow_rest_connectome_e2e", target_runtime="python", params={"dataset_id":"ds000114"}.',
  'Return the exact recipe command, required inputs, expected artifacts, and any blockers before claiming execution is possible.',
].join(' ')

const FUNCTION_GROUPS = [
  {
    title: 'Health checks',
    tools: ['server_info', 'system_self_test'],
    detail: 'Use before claiming the MCP server is connected, healthy, or able to access runtime resources.',
  },
  {
    title: 'Find workflows and evidence',
    tools: ['workflow_search', 'tool_search', 'kg_search_nodes', 'kg_search_datasets'],
    detail: 'Use to map a user question to workflows, tools, datasets, tasks, and KG evidence.',
  },
  {
    title: 'Prepare execution handoff',
    tools: ['get_execution_recipe', 'plan_preflight', 'plan_create'],
    detail: 'Use for runnable local, container, Neurodesk, or cluster recipes. These tools prepare plans; they do not prove execution happened.',
  },
  {
    title: 'Validate before running',
    tools: ['pipeline_plan_validate', 'pipeline_plan_review', 'qsm_implementation_review'],
    detail: 'Use when a plan or implementation needs schema, path, modality, ordering, or domain checks.',
  },
  {
    title: 'Inspect runs and artifacts',
    tools: ['run_get', 'run_logs', 'artifact_list', 'artifact_read_text'],
    detail: 'Use only when the active MCP client exposes run or artifact tools for the relevant persisted run.',
  },
]

function CodeBlock({
  value,
  label,
  copyLabel,
}: {
  value: string
  label: string
  copyLabel: string
}) {
  const { toast } = useToast()

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      toast({ title: `Copied ${copyLabel}` })
    } catch {
      toast({ title: `Failed to copy ${copyLabel}`, variant: 'destructive' })
    }
  }

  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <Button type="button" size="sm" variant="secondary" onClick={() => void copy()}>
          <Copy className="mr-2 h-3 w-3" />
          Copy {copyLabel}
        </Button>
      </div>
      <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{value}</pre>
    </div>
  )
}

export function McpSetupGuide() {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-white p-5">
        <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-2">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Terminal setup and live checks
            </div>
            <h2 className="text-lg font-semibold text-gray-900">Run Brain Researcher with MCP</h2>
            <p className="text-sm text-muted-foreground">
              Configure the token once, connect Codex, Cursor, or Claude Code, then ask the agent
              to run health checks before requesting workflow recipes.
            </p>
          </div>
          <div className="rounded border bg-muted/20 p-3 text-xs text-muted-foreground">
            Keep <code className="font-mono">BR_MCP_TOKEN</code> as the raw{' '}
            <code className="font-mono">brk_...</code> token. Do not put{' '}
            <code className="font-mono">Bearer </code> inside the token value.
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">1. Put the token in your shell</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Use <code className="font-mono">~/.zshrc</code> on macOS/zsh, or the matching shell
            profile for your terminal.
          </p>
        </div>
        <CodeBlock value={TERMINAL_SETUP} label="Terminal" copyLabel="terminal setup" />
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            2. Check the connection in your agent
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Start the interactive client after reloading the shell, then paste one of these prompts.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <CodeBlock
            value={SMOKE_PROMPT_CODEX}
            label="Codex prompt"
            copyLabel="Codex smoke prompt"
          />
          <CodeBlock
            value={SMOKE_PROMPT_CLAUDE}
            label="Claude Code prompt"
            copyLabel="Claude Code smoke prompt"
          />
        </div>
        <div className="rounded-lg border p-3 text-xs text-muted-foreground">
          Expected result: <code className="font-mono">server_info</code> returns{' '}
          <code className="font-mono">ok=true</code>, and{' '}
          <code className="font-mono">system_self_test</code> returns{' '}
          <code className="font-mono">overall=pass</code>. If a client cannot see those tools, ask
          it to inspect the exposed MCP tool names before trying another function.
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">3. Ask for a workflow handoff</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This example prepares a recipe. It should not be described as completed hosted
            execution unless artifacts are actually produced and inspected.
          </p>
        </div>
        <CodeBlock
          value={HANDOFF_PROMPT}
          label="Example MCP handoff prompt"
          copyLabel="handoff prompt"
        />
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Agent rules to give users</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            These are the public-facing version of the repo&apos;s Brain Researcher MCP agent rules.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border p-4 text-sm">
            <div className="font-medium text-gray-900">Required first check</div>
            <ul className="mt-2 list-disc space-y-2 pl-4 text-muted-foreground">
              <li>Confirm the Brain Researcher MCP server is active.</li>
              <li>Inspect the actual exposed tool names before invoking a function.</li>
              <li>Run health checks before claiming execution, validation, or data access.</li>
              <li>If MCP is unavailable, say that directly and continue with the closest fallback.</li>
            </ul>
          </div>
          <div className="rounded-lg border p-4 text-sm">
            <div className="font-medium text-gray-900">Execution boundary</div>
            <ul className="mt-2 list-disc space-y-2 pl-4 text-muted-foreground">
              <li>
                <code className="font-mono">get_execution_recipe</code> returns a recipe, not a
                completed analysis.
              </li>
              <li>Hosted Studio may be credit-gated, degraded, or blocked while MCP remains usable.</li>
              <li>Success means expected artifacts, logs, and run manifests were produced and checked.</li>
              <li>Dangerous/admin execution tools should only be used when the user asks for them.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Common MCP functions</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              The active client may expose only a subset. Ask it to inspect the tool list first.
            </p>
          </div>
          <Button asChild type="button" size="sm" variant="outline">
            <Link href={STARTER_REPO_URL} target="_blank" rel="noreferrer">
              <ExternalLink className="mr-2 h-3.5 w-3.5" />
              Open starter repo
            </Link>
          </Button>
        </div>
        <div className="grid gap-3">
          {FUNCTION_GROUPS.map((group) => (
            <div key={group.title} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-gray-900">{group.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{group.detail}</div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {group.tools.map((tool) => (
                    <code
                      key={tool}
                      className="rounded border bg-muted/20 px-1.5 py-0.5 font-mono text-xs"
                    >
                      {tool}
                    </code>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

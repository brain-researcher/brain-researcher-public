export const DEFAULT_MCP_CLOUD_URL = 'https://${PUBLIC_HOSTNAME}/mcp'
export const MCP_TOKEN_PLACEHOLDER = 'brk_<kid>.<secret>'

export type HostedMcpClient = 'cursor' | 'codex' | 'claude'

export type HostedMcpSnippet = {
  copyButtonLabel: string
  copyLabel: string
  fileName: string
  snippet: string
}

function buildCursorSnippet(url: string, directToken: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        'brain-researcher': {
          type: 'http',
          url,
          headers: {
            Authorization: `Bearer ${directToken}`,
            Accept: 'application/json, text/event-stream',
          },
        },
      },
    },
    null,
    2,
  )
}

function buildCodexSnippet(url: string): string {
  return [
    '[mcp_servers.brain-researcher]',
    `url = "${url}"`,
    'bearer_token_env_var = "BR_MCP_TOKEN"',
    '',
    '[mcp_servers.brain-researcher.http_headers]',
    'Accept = "application/json, text/event-stream"',
  ].join('\n')
}

function buildClaudeSnippet(url: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        'brain-researcher': {
          type: 'http',
          url,
          headers: {
            Authorization: 'Bearer ${BR_MCP_TOKEN}',
            Accept: 'application/json, text/event-stream',
          },
        },
      },
    },
    null,
    2,
  )
}

export function buildHostedMcpSnippet(
  client: HostedMcpClient,
  options?: {
    directToken?: string
    url?: string
  },
): HostedMcpSnippet {
  const url = (options?.url || DEFAULT_MCP_CLOUD_URL).trim()
  const directToken = (options?.directToken || MCP_TOKEN_PLACEHOLDER).trim()

  switch (client) {
    case 'cursor':
      return {
        copyButtonLabel: 'Copy JSON',
        copyLabel: 'Cursor JSON',
        fileName: 'mcp.json',
        snippet: buildCursorSnippet(url, directToken),
      }
    case 'codex':
      return {
        copyButtonLabel: 'Copy TOML',
        copyLabel: 'Codex TOML',
        fileName: '~/.codex/config.toml',
        snippet: buildCodexSnippet(url),
      }
    case 'claude':
      return {
        copyButtonLabel: 'Copy JSON',
        copyLabel: 'Claude Code JSON',
        fileName: '.mcp.json',
        snippet: buildClaudeSnippet(url),
      }
  }
}

export function buildMcpTokenExportCommand(token?: string): string {
  const tokenValue = (token || MCP_TOKEN_PLACEHOLDER).trim()
  return [
    '# Brain Researcher MCP',
    `export BR_MCP_TOKEN="${tokenValue}"`,
    'export BR_MCP_AUTH_HEADER="Bearer ${BR_MCP_TOKEN}"',
  ].join('\n')
}

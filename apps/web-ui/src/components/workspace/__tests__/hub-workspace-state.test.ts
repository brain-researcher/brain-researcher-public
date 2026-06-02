import { describe, expect, it } from 'vitest'

import {
  buildHubRuntimeTargetUrl,
  handoffAllowsDirectRuntimeOpen,
  handoffHasRuntimeTarget,
  handoffNeedsRuntimePolling,
  parseHubLaunchRequest,
} from '@/components/workspace/hub-workspace-state'

describe('parseHubLaunchRequest', () => {
  it('uses hosted defaults when the hub is opened without explicit params', () => {
    const parsed = parseHubLaunchRequest(new URLSearchParams())

    expect(parsed.sessionId).toBeNull()
    expect(parsed.createPayload.project_id).toBe('proj_workspace')
    expect(parsed.createPayload.display_name).toBe('Hosted Workspace')
    expect(parsed.createPayload.attach_if_exists).toBe(true)
    expect(parsed.handoffPayload.target_path).toBeNull()
    expect(parsed.handoffPayload.notebook_path).toBeNull()
  })

  it('routes .py paths into notebook handoff payloads', () => {
    const parsed = parseHubLaunchRequest(
      new URLSearchParams({
        session_id: 'studio_abc123',
        path: 'projects/proj_x/notebooks/demo.py',
        focus: 'editor',
        materialize_notebook_if_needed: '1',
      }),
    )

    expect(parsed.sessionId).toBe('studio_abc123')
    expect(parsed.handoffPayload.notebook_path).toBe('projects/proj_x/notebooks/demo.py')
    expect(parsed.handoffPayload.target_path).toBeNull()
    expect(parsed.handoffPayload.initial_focus).toBe('editor')
    expect(parsed.handoffPayload.materialize_notebook_if_needed).toBe(true)
  })

  it('routes non-notebook paths into target_path and preserves create metadata', () => {
    const parsed = parseHubLaunchRequest(
      new URLSearchParams({
        project_id: 'proj_custom',
        display_name: 'Custom Hub Session',
        path: 'projects/proj_custom/data',
        artifact_id: 'artifact_123',
        open_clean_workspace: 'true',
      }),
    )

    expect(parsed.createPayload.project_id).toBe('proj_custom')
    expect(parsed.createPayload.display_name).toBe('Custom Hub Session')
    expect(parsed.handoffPayload.target_path).toBe('projects/proj_custom/data')
    expect(parsed.handoffPayload.notebook_path).toBeNull()
    expect(parsed.handoffPayload.open_artifact_id).toBe('artifact_123')
    expect(parsed.handoffPayload.open_clean_workspace).toBe(true)
  })

  it('maps TaskBeacon launch params into a fresh hub session and default target path', () => {
    const parsed = parseHubLaunchRequest(
      new URLSearchParams({
        taskbeacon_repo: 'TaskBeacon/T000015-ant',
        taskbeacon_ref: 'main',
      }),
    )

    expect(parsed.sessionId).toBeNull()
    expect(parsed.createPayload.display_name).toBe('TaskBeacon · T000015-ant')
    expect(parsed.createPayload.attach_if_exists).toBe(false)
    expect(parsed.createPayload.taskbeacon_repo).toBe('TaskBeacon/T000015-ant')
    expect(parsed.createPayload.taskbeacon_ref).toBe('main')
    expect(parsed.handoffPayload.target_path).toBe(
      'projects/proj_workspace/taskbeacon/T000015-ant',
    )
  })
})

describe('handoffHasRuntimeTarget', () => {
  it('detects whether a hub handoff exposes a runtime target URL', () => {
    expect(handoffHasRuntimeTarget(null)).toBe(false)
    expect(
      handoffHasRuntimeTarget({
        runtime_target_url: 'https://runtime.example/studio_123',
      } as never),
    ).toBe(true)
  })
})

describe('handoffNeedsRuntimePolling', () => {
  it('continues polling until the runtime target is marked ready', () => {
    expect(handoffNeedsRuntimePolling(null)).toBe(true)
    expect(
      handoffNeedsRuntimePolling({
        runtime_target_url: 'https://runtime.example/studio_123',
        runtime_target_ready: false,
      } as never),
    ).toBe(true)
    expect(
      handoffNeedsRuntimePolling({
        runtime_target_url: 'https://runtime.example/studio_123',
        runtime_target_ready: true,
      } as never),
    ).toBe(false)
  })
})

describe('handoffAllowsDirectRuntimeOpen', () => {
  it('only allows direct opens once the runtime target is marked ready', () => {
    expect(handoffAllowsDirectRuntimeOpen(null)).toBe(false)
    expect(
      handoffAllowsDirectRuntimeOpen({
        runtime_target_url: 'https://runtime.example/studio_123',
        runtime_target_ready: false,
      } as never),
    ).toBe(false)
    expect(
      handoffAllowsDirectRuntimeOpen({
        runtime_target_url: 'https://runtime.example/studio_123',
        runtime_target_ready: true,
      } as never),
    ).toBe(true)
  })
})

describe('buildHubRuntimeTargetUrl', () => {
  it('does NOT impose the studio session id on the runtime target URL', () => {
    // marimo owns its own session id now; the studio id must not be threaded in.
    expect(
      buildHubRuntimeTargetUrl(
        'https://brain-researcher.com/hub/br-marimo-rt-demo/',
        'studio_demo123',
      ),
    ).toBe('https://brain-researcher.com/hub/br-marimo-rt-demo/')
  })

  it('preserves other query params while stripping any session_id', () => {
    expect(
      buildHubRuntimeTargetUrl(
        'https://brain-researcher.com/hub/br-marimo-rt-demo/?path=projects%2Fdemo&session_id=studio_demo123',
        'studio_demo123',
      ),
    ).toBe(
      'https://brain-researcher.com/hub/br-marimo-rt-demo/?path=projects%2Fdemo',
    )
  })

  it('returns the original URL when no session id is available', () => {
    expect(
      buildHubRuntimeTargetUrl(
        'https://brain-researcher.com/hub/br-marimo-rt-demo/',
        null,
      ),
    ).toBe('https://brain-researcher.com/hub/br-marimo-rt-demo/')
  })
})

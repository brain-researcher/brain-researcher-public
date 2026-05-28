# StepsList Component Integration Guide

## Overview

The `StepsList` component provides real-time pipeline step monitoring with SSE streaming support. This guide shows how to integrate it into existing pages.

## Quick Start

### Basic Usage

```tsx
import { StepsList } from "@/components/landing/StepsList";

export function MyJobPage({ jobId }: { jobId: string }) {
  return (
    <div>
      <h2>Pipeline Steps</h2>
      <StepsList jobId={jobId} enableStreaming={true} />
    </div>
  );
}
```

## Component Props

### StepsList

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `jobId` | `string` | required | Job ID to fetch steps for |
| `enableStreaming` | `boolean` | `true` | Enable SSE streaming for real-time updates |

## Features

- ✅ Real-time updates via Server-Sent Events
- ✅ Automatic fallback to polling if SSE fails
- ✅ Color-coded status badges
- ✅ Per-step log viewing
- ✅ Error display with truncation
- ✅ Loading states
- ✅ Completion detection

## API Endpoints

The component uses the analysis-scoped same-origin routes:

- `GET /api/analyses/{analysis_id}/steps` - Fetch current steps (polling)
- `GET /api/analyses/{analysis_id}/steps/stream` - SSE stream for real-time updates
- `GET /api/analyses/{analysis_id}/logs/stream?run_dir={path}` - Per-step logs

These routes proxy to the canonical Orchestrator `/api/jobs/*` endpoints, so
browser traffic stays same-origin.

## Styling

The component uses Tailwind CSS and shadcn/ui components. It's responsive and follows the existing design system.

## Example: Standalone Job Page

Create `src/app/jobs/[jobId]/page.tsx`:

```tsx
import { StepsList } from "@/components/landing/StepsList";

export default function JobPage({
  params
}: {
  params: { jobId: string }
}) {
  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">Job {params.jobId}</h1>

        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">Pipeline Steps</h2>
          <StepsList jobId={params.jobId} enableStreaming={true} />
        </div>
      </div>
    </div>
  );
}

export const dynamic = 'force-dynamic';
```

## Testing

To test the component:

1. Start the orchestrator service
2. Submit a multi-step analysis/job
3. Navigate to the page with StepsList
4. Verify:
   - Steps appear as they execute
   - Real-time updates work
   - Status badges change colors
   - "View Logs" button opens logs

## Troubleshooting

### SSE Connection Fails

The component automatically falls back to polling. Check:
- Network tab for SSE connection status
- Backend logs for SSE errors
- CORS configuration if accessing from different origin

### Steps Not Appearing

- Check that the job has `run_dir` set
- Verify provenance.json exists and contains `child_runs`
- Check browser console for same-origin `/api/analyses/*` errors

### Logs Button Not Working

- Ensure step has `run_dir` field populated
- Verify log streaming endpoint is accessible
- Check that logs exist in the step's run directory

## Notes

`StepsList` is intended to be embedded in analysis/run pages that already have
an analysis or job ID available.

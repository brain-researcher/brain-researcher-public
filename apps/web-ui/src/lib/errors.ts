// Centralized error taxonomy + UI rendering hints.
// Keep strings minimal; UI components decide final copy.

export type ErrorRenderKind = 'inline' | 'toast' | 'fullscreen';

export type ErrorCode =
  | 'E-INPUT-VALIDATION'
  | 'E-AUTH'
  | 'E-FORBIDDEN'
  | 'E-TOOL-PREFLIGHT'
  | 'E-STREAM-DROP'
  | 'E-KG-OFFLINE'
  | 'E-LLM-RATE'
  | 'E-RUN-FAILED'
  | 'E-SERVICE-UNAVAILABLE'
  | 'E-UNKNOWN';

export type RenderPlan = {
  kind: ErrorRenderKind;
  fallbackAction?: 'retry' | 'login' | 'new-thread' | 'model-fallback';
  message?: string;
};

const DEFAULT_PLAN: RenderPlan = { kind: 'toast' };

export function planForError(code?: string): RenderPlan {
  switch (code as ErrorCode) {
    case 'E-INPUT-VALIDATION':
      return { kind: 'inline', fallbackAction: 'retry' };
    case 'E-AUTH':
      return { kind: 'fullscreen', fallbackAction: 'login' };
    case 'E-FORBIDDEN':
      return { kind: 'toast', fallbackAction: 'new-thread' };
    case 'E-TOOL-PREFLIGHT':
      return { kind: 'inline', fallbackAction: 'retry' };
    case 'E-STREAM-DROP':
      return { kind: 'inline', fallbackAction: 'retry' };
    case 'E-KG-OFFLINE':
      return { kind: 'toast', fallbackAction: 'model-fallback' };
    case 'E-LLM-RATE':
      return { kind: 'toast', fallbackAction: 'retry' };
    case 'E-RUN-FAILED':
      return { kind: 'inline', fallbackAction: 'retry' };
    case 'E-SERVICE-UNAVAILABLE':
      return { kind: 'toast', fallbackAction: 'retry' };
    default:
      return DEFAULT_PLAN;
  }
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;
  if (typeof body === 'string') return undefined;
  if (body.code) return body.code;
  if (body.error && typeof body.error === 'string') return body.error;
  if (body.detail && typeof body.detail === 'object' && typeof body.detail.code === 'string') {
    return body.detail.code;
  }
  return undefined;
}

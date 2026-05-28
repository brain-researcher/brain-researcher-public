import type { DatasetSearchResponse } from '@/types/datasets-search'
import { resolveRealtimeWsBaseUrl } from './service-endpoints'

const DEFAULT_TIMEOUT_MS = 8000;

type FetchOptions = RequestInit & {
  timeoutMs?: number;
};

// Types for orchestrator job API
type SubmitRunPayload = {
  prompt: string;
  pipeline?: string;
  datasetId?: string;
  parameters?: Record<string, any>;
  copilot?: boolean;
  attachments?: any[];
  scenarioId?: string;
  checkpointId?: string | null;
};

type SubmitRunResponse = {
  job_id: string;
};

type JobStatus = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  steps?: any[];
  artifacts?: any[];
  error?: string;
  progress?: any;
  metadata?: Record<string, any>;
  plan_summary?: {
    plan_id?: string;
    version?: number;
    resolvable?: boolean;
    step_count?: number;
    por_token_set?: boolean;
    plan_status?: string;
    plan_conf?: number;
    confidence_score?: number;
  };
};

function resolveServerOrigin(): string {
  if (typeof window !== "undefined") {
    return "";
  }

  const hostCandidate =
    process.env.NEXT_SERVER_HOST ||
    process.env.HOST ||
    "127.0.0.1";
  const host = hostCandidate === "0.0.0.0" ? "127.0.0.1" : hostCandidate;
  const port = process.env.NEXT_SERVER_PORT || process.env.PORT || "3000";
  const protocol = process.env.NEXT_SERVER_PROTOCOL || "http";
  const computedOrigin = `${protocol}://${host}:${port}`.replace(/\/$/, "");

  const explicitOrigin =
    process.env.NEXT_INTERNAL_UI_ORIGIN ||
    process.env.NEXT_PUBLIC_SITE_URL ||
    (process.env.NODE_ENV === "production" ? process.env.FRONTEND_URL : undefined);

  if (explicitOrigin) {
    return explicitOrigin.replace(/\/$/, "");
  }

  return computedOrigin;
}

const SERVER_ORIGIN = resolveServerOrigin();

function buildRequestUrl(path: string): string {
  const normalized = path ? (path.startsWith("/") ? path : `/${path}`) : "/";
  if (typeof window === "undefined") {
    return `${SERVER_ORIGIN}${normalized}`;
  }
  return normalized;
}

async function fetchWithTimeout(
  url: string,
  { timeoutMs = DEFAULT_TIMEOUT_MS, ...init }: FetchOptions = {},
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      cache: init.cache ?? "no-store",
    });
    return response;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function getJSON<T>(path: string, options?: FetchOptions): Promise<T> {
  const response = await fetchWithTimeout(buildRequestUrl(path), options);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Request failed (${response.status}): ${body || response.statusText}`);
  }

  return (await response.json()) as T;
}

// Simple EventSource wrapper that resolves the correct origin on the server and client.
export function openSSE(path: string): EventSource {
  const url = buildRequestUrl(path);
  return new EventSource(url);
}

export const apiClient = {
  // Generic HTTP helpers (used by hooks like useSurvey)
  async get(path: string, init?: FetchOptions) {
    return fetchWithTimeout(buildRequestUrl(path), { ...init, method: init?.method ?? 'GET' });
  },

  async post(path: string, body?: any, init?: FetchOptions) {
    return fetchWithTimeout(buildRequestUrl(path), {
      ...init,
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
      body: body != null ? JSON.stringify(body) : init?.body,
    });
  },

  async put(path: string, body?: any, init?: FetchOptions) {
    return fetchWithTimeout(buildRequestUrl(path), {
      ...init,
      method: 'PUT',
      headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
      body: body != null ? JSON.stringify(body) : init?.body,
    });
  },

  async delete(path: string, init?: FetchOptions) {
    return fetchWithTimeout(buildRequestUrl(path), { ...init, method: 'DELETE' });
  },

  async getDatasets(params?: {
    limit?: number;
    offset?: number;
    search?: string;
    modalities?: string[];
    source_repo?: string[];
    category?: string[];
    access_type?: string[];
    sort?: 'relevance' | 'subjects' | 'updated';
  }): Promise<DatasetSearchResponse> {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set('limit', String(params.limit));
    if (params?.offset != null) search.set('offset', String(params.offset));
    if (params?.search) search.set('q', params.search);
    params?.modalities?.forEach((value) => search.append('modalities', value));
    params?.source_repo?.forEach((value) => search.append('source_repo', value));
    params?.category?.forEach((value) => search.append('category', value));
    params?.access_type?.forEach((value) => search.append('access_type', value));
    if (params?.sort) search.set('sort', params.sort);
    const suffix = search.toString();
    const query = suffix ? `?${suffix}` : '';
    return getJSON(`/api/catalog/datasets/search${query}`);
  },

};

// Backwards compatibility alias
export const api = apiClient;

export default apiClient;

// Public Web UI analysis helpers.
// `/api/analyses/*` is the browser-facing analysis facade backed by the
// Orchestrator `/run` + job/analysis APIs.
const ANALYSES_BASE = '/api/analyses';

export async function submitRun(prompt: string, payload: Omit<SubmitRunPayload, 'prompt'> = {}): Promise<SubmitRunResponse> {
  const { attachments, checkpointId, copilot, datasetId, parameters, pipeline, scenarioId } = payload
  const response = await fetchWithTimeout(buildRequestUrl(ANALYSES_BASE), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      plan: {
        prompt,
        pipeline: pipeline || 'chat',
        ...(datasetId ? { dataset_id: datasetId } : {}),
        ...(parameters ? { parameters } : {}),
        ...(copilot ? { copilot: true } : {}),
        ...(attachments?.length ? { attachments } : {}),
        ...(scenarioId ? { scenario_id: scenarioId } : {}),
      },
      ...(checkpointId ? { checkpoint_id: checkpointId } : {}),
      thread: { mode: 'none' },
    }),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`submitRun failed (${response.status}): ${text || response.statusText}`);
  }

  const data = (await response.json()) as any;
  const jobId =
    (data && (data.job_id || data.analysis_id || data.run_id || data.id)) ??
    undefined;
  if (!jobId) {
    throw new Error('submitRun failed: missing job id');
  }
  return { job_id: String(jobId) };
}

export async function cancelJob(jobId: string): Promise<void> {
  const url = buildRequestUrl(`${ANALYSES_BASE}/${encodeURIComponent(jobId)}/cancel`);
  const response = await fetchWithTimeout(url, { method: 'POST' });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`cancelJob failed (${response.status}): ${text || response.statusText}`);
  }
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const url = buildRequestUrl(`${ANALYSES_BASE}/${encodeURIComponent(jobId)}`);
  const response = await fetchWithTimeout(url, { method: 'GET' });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`getJob failed (${response.status}): ${text || response.statusText}`);
  }
  const payload = (await response.json()) as any;
  if (payload && typeof payload === 'object' && payload.job) {
    return payload.job as JobStatus;
  }
  return payload as JobStatus;
}

export function createWebSocket(jobId: string): WebSocket {
  const wsBase = resolveRealtimeWsBaseUrl().replace(/\/$/, '');
  return new WebSocket(`${wsBase}/jobs/${encodeURIComponent(jobId)}`);
}

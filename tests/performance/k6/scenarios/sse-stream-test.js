/**
 * Server-Sent Events (SSE) Load Test
 * ----------------------------------
 * Exercises the orchestrator's /api/jobs/{id}/stream endpoint with
 * concurrent clients to ensure live-progress streaming stays healthy
 * under fan-out load.
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import { Trend, Counter, Rate } from 'k6/metrics';
import { CONFIG } from '../config/k6.config.js';
import { TestDataGenerator } from '../scripts/utils.js';

export const options = {
  stages: [
    { duration: '30s', target: 5 },
    { duration: '2m', target: 25 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    sse_stream_duration: ['p(95)<5000'],
    sse_errors: ['count<5'],
  },
  summaryTrendStats: ['avg', 'min', 'max', 'p(90)', 'p(95)'],
};

const orchestratorUrl = CONFIG.ORCHESTRATOR_URL;
const sseConnectionLatency = new Trend('sse_connection_latency', true);
const sseStreamDuration = new Trend('sse_stream_duration', true);
const ssePayloadSize = new Trend('sse_payload_bytes', true);
const sseErrors = new Counter('sse_errors');
const sseSuccess = new Counter('sse_success');
const sseFallbacks = new Counter('sse_fallbacks');
const sseTimeoutRate = new Rate('sse_timeout_rate');

function makeHeaders(traceId) {
  return {
    headers: {
      'Content-Type': 'application/json',
      'X-Trace-Id': traceId,
    },
    tags: { name: 'create_run' },
  };
}

export default function () {
  group('SSE stream lifecycle', () => {
    const traceId = `k6-trace-${__VU}-${Date.now()}`;
    const prompt = TestDataGenerator.generateFMRIQuery();
    const payload = JSON.stringify({
      prompt,
      pipeline: 'chat',
      parameters: { copilot: true },
    });

    const runResponse = http.post(
      `${orchestratorUrl}/run`,
      payload,
      makeHeaders(traceId)
    );

    const created = check(runResponse, {
      'run created successfully': (r) => r.status === 200,
      'run returns job id': (r) => {
        try {
          const body = JSON.parse(r.body);
          return typeof body.job_id === 'string';
        } catch (err) {
          return false;
        }
      },
    });

    if (!created) {
      sseErrors.add(1);
      return;
    }

    const jobId = JSON.parse(runResponse.body).job_id;
    const streamUrl = `${orchestratorUrl}/api/jobs/${jobId}/stream`;

    const streamStart = Date.now();
    const streamResponse = http.get(streamUrl, {
      timeout: '30s',
      headers: { Accept: 'text/event-stream', 'X-Trace-Id': traceId },
      tags: { name: 'sse_stream' },
    });

    const streamDuration = Date.now() - streamStart;
    sseStreamDuration.add(streamDuration);
    sseConnectionLatency.add(streamResponse.timings.waiting);
    ssePayloadSize.add(streamResponse.body ? streamResponse.body.length : 0);

    const ok = check(streamResponse, {
      'stream responded with 200': (r) => r.status === 200,
      'stream emitted events': (r) => (r.body || '').includes('event:'),
    });

    if (!ok) {
      sseErrors.add(1);
      if (streamResponse.timings.duration >= 30000) {
        sseTimeoutRate.add(1);
      }
      return;
    }

    sseSuccess.add(1);

    if (!streamResponse.body || streamResponse.body.length < 32) {
      sseFallbacks.add(1);
      const pollResponse = http.get(`${orchestratorUrl}/api/jobs/${jobId}`, {
        tags: { name: 'sse_poll_fallback' },
      });
      check(pollResponse, {
        'poll fallback succeeded': (r) => r.status === 200,
      });
    }

    sleep(0.5);
  });
}

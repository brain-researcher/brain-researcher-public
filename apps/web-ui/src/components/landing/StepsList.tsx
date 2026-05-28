"use client";

import { useEffect, useRef, useState } from "react";
import { Copy, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { JobStepsResponse, StepSummary } from "@/lib/job-steps";
import { getJSON, openSSE } from "@/lib/api";


interface StepsListProps {
  jobId: string;
  enableStreaming?: boolean;
  onAskAgent?: (prompt: string) => void;
}

function tailText(value: string, maxChars: number) {
  if (!value) return "";
  if (value.length <= maxChars) return value;
  return value.slice(value.length - maxChars);
}

function buildAskAgentPrompt(args: {
  jobId: string;
  step: StepSummary;
  stream?: "stdout" | "stderr";
  logText?: string;
}) {
  const { jobId, step, stream, logText } = args;
  const lines: string[] = [];
  lines.push("Help me diagnose this pipeline step and propose a fix.");
  lines.push(`Job ID: ${jobId}`);
  lines.push(`Step: ${step.name || step.step_id} (${step.step_id})`);
  lines.push(`State: ${step.state}`);
  lines.push(`Run dir: ${step.run_dir || "—"}`);
  if (step.error) {
    lines.push("Error:");
    lines.push(step.error);
  }
  if (logText && stream) {
    lines.push("");
    lines.push(`Recent ${stream} logs (tail):`);
    lines.push(tailText(logText, 2000));
  }
  lines.push("");
  lines.push("Please provide concrete next steps and what to change before retrying.");
  return lines.join("\n");
}

const TERMINAL_JOB_STATES = new Set(["completed", "succeeded", "failed", "timeout", "cancelled", "skipped"]);
const FAILED_JOB_STATES = new Set(["failed", "timeout"]);
const PENDING_LIKE_STEP_STATES = new Set(["", "pending", "queued", "claimed", "unknown"]);

function normalizeState(value?: string | null) {
  return (value || "").trim().toLowerCase();
}

function jobSummaryLabel(data: JobStepsResponse | null, isComplete: boolean) {
  const state = normalizeState(data?.state);
  if (state === "failed") return "Job failed";
  if (state === "timeout") return "Job timed out";
  if (state === "cancelled") return "Job cancelled";
  if (state === "skipped") return "Job skipped";
  if (state === "completed" || state === "succeeded" || isComplete) return "Job completed";
  return "Job in progress";
}

function displayStepState(stepState: string, jobState?: string | null) {
  const normalizedStep = normalizeState(stepState);
  const normalizedJob = normalizeState(jobState);
  if (FAILED_JOB_STATES.has(normalizedJob) && PENDING_LIKE_STEP_STATES.has(normalizedStep)) {
    return normalizedJob;
  }
  return normalizedStep || stepState;
}

function missingLogsLabel(stepState: string, jobState?: string | null) {
  const normalizedStep = normalizeState(stepState);
  const normalizedJob = normalizeState(jobState);
  if (
    FAILED_JOB_STATES.has(normalizedJob) ||
    FAILED_JOB_STATES.has(normalizedStep) ||
    (TERMINAL_JOB_STATES.has(normalizedJob) && PENDING_LIKE_STEP_STATES.has(normalizedStep))
  ) {
    return "No step logs captured";
  }
  return "Logs unavailable";
}

export function StepsList({
  jobId,
  enableStreaming = true,
  onAskAgent,
}: StepsListProps) {
  const [data, setData] = useState<JobStepsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedStep, setSelectedStep] = useState<StepSummary | null>(null);
  const [logStream, setLogStream] = useState<"stdout" | "stderr">("stdout");

  useEffect(() => {
    let isMounted = true;
    let sse: EventSource | null = null;
    let pollInterval: NodeJS.Timeout | null = null;

    const cleanup = () => {
      if (sse) {
        sse.close();
        sse = null;
      }
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
      isMounted = false;
    };

    const fetchSteps = async () => {
      try {
        const json = await getJSON<JobStepsResponse>(
          `/api/analyses/${encodeURIComponent(jobId)}/steps`,
        );
        if (!isMounted) return;
        setData(json);
        setIsLoading(false);
        setError(null);
      } catch (e) {
        if (!isMounted) return;
        setError(e instanceof Error ? e.message : "Unknown error");
        setIsLoading(false);
      }
    };

    const startPolling = () => {
      if (!pollInterval) {
        pollInterval = setInterval(fetchSteps, 3000);
      }
    };

    if (!enableStreaming) {
      fetchSteps();
      startPolling();
      return () => cleanup();
    }

    // Prime initial state before SSE updates arrive
    fetchSteps();

    try {
      sse = openSSE(`/api/analyses/${encodeURIComponent(jobId)}/steps/stream`);
    } catch (err) {
      if (isMounted) {
        setError("Failed to establish SSE connection; switching to polling.");
        setIsLoading(false);
      }
      startPolling();
      return () => cleanup();
    }

    sse.addEventListener("steps_update", (evt) => {
      const message = evt as MessageEvent;
      try {
        const update: JobStepsResponse = JSON.parse(message.data);
        if (!isMounted) return;
        setData(update);
        setIsLoading(false);
        setIsComplete(false);
        setError(null);
      } catch (parseErr) {
        console.error("Failed to parse steps_update event", parseErr);
      }
    });

    sse.addEventListener("complete", (evt) => {
      const message = evt as MessageEvent;
      try {
        JSON.parse(message.data);
      } catch (parseErr) {
        console.error("Failed to parse complete event", parseErr);
      }
      if (!isMounted) return;
      setIsComplete(true);
      setError(null);
    });

    const handleSseError = (evt: Event) => {
      const message = evt as MessageEvent;
      if (isMounted) {
        if (message?.data) {
          try {
            const payload = JSON.parse(message.data);
            setError(payload.error || "SSE connection lost; switching to polling.");
          } catch {
            setError("SSE connection lost; switching to polling.");
          }
        } else {
          setError("SSE connection lost; switching to polling.");
        }
        setIsLoading(false);
      }
      if (sse) {
        sse.close();
        sse = null;
      }
      startPolling();
    };

    sse.addEventListener("error", handleSseError);
    sse.onerror = handleSseError;

    return () => cleanup();
  }, [jobId, enableStreaming]);

  const handleOpenLogs = (step: StepSummary) => {
    setSelectedStep(step);
    setLogStream("stdout");
  };

  const handleDialogChange = (open: boolean) => {
    if (!open) {
      setSelectedStep(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Loading step summaries…</span>
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!data) {
    return (
      <Alert>
        <AlertDescription>No step data available.</AlertDescription>
      </Alert>
    );
  }

  if (data.steps.length === 0) {
    return (
      <Alert>
        <AlertDescription>
          No steps available yet. Steps will appear as the pipeline executes.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {jobSummaryLabel(data, isComplete)}
        </p>
        {data.cache_hit && (
          <Badge variant="outline" className="bg-emerald-50 text-emerald-700">
            From cache
          </Badge>
        )}
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide">
            <tr>
              <th className="p-3 text-left font-semibold">Step</th>
              <th className="p-3 text-left font-semibold">Status</th>
              <th className="p-3 text-left font-semibold">Duration</th>
              <th className="p-3 text-left font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.steps.map((step) => (
              <tr key={step.step_id} className="border-t">
                <td className="p-3 align-top">
                  <div className="font-medium text-foreground">
                    {step.name || step.step_id}
                  </div>
                  {step.error && (
                    <div
                      className="mt-1 max-w-lg text-xs text-destructive"
                      title={step.error}
                    >
                      Error: {step.error.length > 120 ? `${step.error.slice(0, 117)}…` : step.error}
                    </div>
                  )}
                </td>
                <td className="p-3 align-top">
                  <StepStatusBadge state={step.state} jobState={data.state} />
                </td>
                <td className="p-3 align-top text-xs text-muted-foreground">
                  {typeof step.execution_time_ms === "number"
                    ? `${(step.execution_time_ms / 1000).toFixed(2)}s`
                    : "—"}
                </td>
                <td className="p-3 align-top">
                  <div className="flex flex-wrap items-center gap-2">
                    {step.run_dir ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleOpenLogs(step)}
                      >
                        View logs
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {missingLogsLabel(step.state, data.state)}
                      </span>
                    )}
                    {onAskAgent ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          onAskAgent(buildAskAgentPrompt({ jobId, step }))
                        }
                      >
                        Ask Agent
                      </Button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isComplete && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="text-green-600">✓</span>
          Pipeline finished – no further updates expected.
        </div>
      )}

      <Dialog open={!!selectedStep} onOpenChange={handleDialogChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              Step logs — {selectedStep?.name || selectedStep?.step_id}
            </DialogTitle>
            <DialogDescription>
              Review the latest logs for this pipeline step.
            </DialogDescription>
          </DialogHeader>
          {selectedStep?.run_dir ? (
            <StepLogViewer
              jobId={jobId}
              step={selectedStep}
              stream={logStream}
              onStreamChange={setLogStream}
              onAskAgent={onAskAgent}
            />
          ) : (
            <Alert>
              <AlertDescription>
                This step has not exposed a run directory yet. Logs will appear once execution starts.
              </AlertDescription>
            </Alert>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StepStatusBadge({ state, jobState }: { state: string; jobState?: string | null }) {
  const stateNormalized = displayStepState(state, jobState);

  const config: Record<
    string,
    { variant: "default" | "secondary" | "destructive" | "outline"; label: string }
  > = {
    pending: { variant: "secondary", label: "Pending" },
    queued: { variant: "secondary", label: "Queued" },
    claimed: { variant: "outline", label: "Claimed" },
    running: { variant: "default", label: "Running" },
    completed: { variant: "outline", label: "Completed" },
    succeeded: { variant: "outline", label: "Succeeded" },
    failed: { variant: "destructive", label: "Failed" },
    timeout: { variant: "destructive", label: "Timeout" },
    cancelled: { variant: "secondary", label: "Cancelled" },
    skipped: { variant: "secondary", label: "Skipped" },
    retrying: { variant: "default", label: "Retrying" },
    review_blocked: { variant: "destructive", label: "Review blocked" },
  };

  const badge = config[stateNormalized] || {
    variant: "secondary" as const,
    label: state,
  };

  return <Badge variant={badge.variant}>{badge.label}</Badge>;
}

interface StepLogViewerProps {
  jobId: string;
  step: StepSummary;
  stream: "stdout" | "stderr";
  onStreamChange: (stream: "stdout" | "stderr") => void;
  onAskAgent?: (prompt: string) => void;
}

function StepLogViewer({
  jobId,
  step,
  stream,
  onStreamChange,
  onAskAgent,
}: StepLogViewerProps) {
  const [logText, setLogText] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isComplete, setIsComplete] = useState(false);
  const [copied, setCopied] = useState(false);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!step.run_dir) {
      setError("Step has not produced logs yet.");
      setIsLoading(false);
      return;
    }

    setLogText("");
    setError(null);
    setIsComplete(false);
    setIsLoading(true);
    setCopied(false);

    const params = new URLSearchParams({
      run_dir: step.run_dir,
      follow: "true",
      stream,
    });

    const source = openSSE(
      `/api/analyses/${encodeURIComponent(jobId)}/logs/stream?${params.toString()}`,
    );

    source.addEventListener("log_chunk", (evt) => {
      const message = evt as MessageEvent;
      try {
        const payload = JSON.parse(message.data);
        const decoded = decodeBase64(payload.data ?? "");
        setLogText((prev) => prev + decoded);
        setIsLoading(false);
      } catch (parseErr) {
        console.error("Failed to parse log_chunk", parseErr);
      }
    });

    source.addEventListener("log_complete", () => {
      setIsComplete(true);
      setIsLoading(false);
      source.close();
    });

    source.addEventListener("error", (evt) => {
      const message = evt as MessageEvent;
      if (message?.data) {
        try {
          const payload = JSON.parse(message.data);
          setError(payload.error || "Log stream error");
        } catch {
          setError("Log stream error");
        }
      } else {
        setError("Log stream error");
      }
      setIsLoading(false);
      source.close();
    });

    return () => {
      source.close();
    };
  }, [jobId, step.run_dir, stream]);

  useEffect(() => {
    if (!logContainerRef.current) return;
    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
  }, [logText]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(logText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error("Failed to copy logs", err);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Stream:</span>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              className="h-6 px-2 text-xs"
              variant={stream === "stdout" ? "default" : "outline"}
              onClick={() => onStreamChange("stdout")}
            >
              stdout
            </Button>
            <Button
              size="sm"
              className="h-6 px-2 text-xs"
              variant={stream === "stderr" ? "default" : "outline"}
              onClick={() => onStreamChange("stderr")}
            >
              stderr
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onAskAgent ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                onAskAgent(buildAskAgentPrompt({ jobId, step, stream, logText }))
              }
              disabled={!logText && !step.error}
            >
              Ask Agent
            </Button>
          ) : null}
          <Button size="sm" variant="outline" onClick={handleCopy} disabled={!logText}>
            <Copy className="mr-2 h-4 w-4" /> {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>

      <div
        ref={logContainerRef}
        className="h-80 overflow-y-auto rounded-md border bg-black p-4 font-mono text-xs text-green-200"
      >
        {isLoading && logText.length === 0 && !error && (
          <div className="flex items-center gap-2 text-green-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Waiting for log output…</span>
          </div>
        )}
        {error && (
          <div className="text-red-400">{error}</div>
        )}
        {!isLoading && !error && logText.length === 0 && (
          <div className="text-green-300/70">No log output yet.</div>
        )}
        {logText && <pre className="whitespace-pre-wrap break-words">{logText}</pre>}
      </div>

      {isComplete && (
        <div className="text-xs text-muted-foreground">
          Log stream finished.
        </div>
      )}
    </div>
  );
}

function decodeBase64(value: string): string {
  try {
    const binaryString = atob(value);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i += 1) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return new TextDecoder().decode(bytes);
  } catch (err) {
    console.error("Failed to decode base64 log chunk", err);
    return "";
  }
}

export default StepsList;

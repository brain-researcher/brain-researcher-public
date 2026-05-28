import { spawnGemini } from "./modes/gemini";
import { proxyCore } from "./modes/proxy";
import { normalizeArgs, parseCommand } from "./compat";

type Mode = "proxy" | "gemini";

export async function run(argv: string[]) {
  const [, , ...rest] = argv;
  let mode: Mode | null = null;
  let verbose = false;

  const passthrough: string[] = [];
  for (const arg of rest) {
    if (arg === "--gemini") {
      mode = "gemini";
      continue;
    }
    if (arg === "--proxy") {
      mode = "proxy";
      continue;
    }
    if (arg === "--verbose" || arg === "-v") {
      verbose = true;
    }
    passthrough.push(arg);
  }

  // Default mode selection:
  // 1) Respect environment override if provided
  if (!mode) {
    const envMode = (process.env.BRAINR_DEFAULT_MODE || "").toLowerCase();
    if (envMode === "gemini" || envMode === "proxy") {
      mode = envMode as Mode;
    }
  }

  // 2) Heuristic: if no explicit mode and user provided only flags that
  //    look like direct prompt invocation (e.g., -p/--prompt/-m/--model)
  //    without a subcommand, prefer Gemini (local OAuth free credits).
  if (!mode) {
    const { command, flags } = parseCommand(passthrough);
    const looksLikeDirectPrompt =
      (!command || command === undefined) &&
      flags.some((f) => ["-p", "--prompt", "-m", "--model", "--json"].includes(f));
    if (looksLikeDirectPrompt) {
      mode = "gemini";
    }
  }

  // 3) Final default: proxy to core service (preserves backwards-compatibility)
  if (!mode) mode = "proxy";

  if (verbose) {
    console.error(`[brainr] mode: ${mode}`);
    console.error(`[brainr] args: ${passthrough.join(" ")}`);
  }

  const normalized = normalizeArgs(passthrough);
  
  if (mode === "gemini") {
    if (verbose) console.error("[brainr] spawning official Gemini CLI...");
    await spawnGemini(normalized);
  } else {
    if (verbose) console.error("[brainr] proxying to core service...");
    await proxyCore(normalized);
  }
}

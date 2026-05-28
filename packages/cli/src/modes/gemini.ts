import { spawn } from "node:child_process";
import { platform } from "node:os";
import { existsSync } from "node:fs";
import { join } from "node:path";

/**
 * Spawn the official Gemini CLI to leverage user's free OAuth credits.
 * This preserves the user's authentication and quota.
 */
export async function spawnGemini(args: string[]) {
  const cmd = findGeminiExecutable();
  
  if (!cmd) {
    console.error("[brainr] Error: Gemini CLI not found!");
    console.error("[brainr] Please install it first:");
    console.error("[brainr]   npm install -g @google/gemini-cli");
    console.error("[brainr]   or");
    console.error("[brainr]   brew install gemini");
    process.exit(1);
  }
  
  await run(cmd, args, { env: process.env });
}

/**
 * Find the Gemini CLI executable.
 * Checks common locations and falls back to PATH.
 */
function findGeminiExecutable(): string | null {
  // First check environment variable override
  if (process.env.GEMINI_CLI) {
    if (existsSync(process.env.GEMINI_CLI)) {
      return process.env.GEMINI_CLI;
    }
  }
  
  // Platform-specific common locations
  const isWindows = platform() === "win32";
  const isDarwin = platform() === "darwin";
  
  const candidates: string[] = [];
  
  if (isWindows) {
    candidates.push(
      "C:\\Program Files\\Google\\Gemini CLI\\gemini.exe",
      "C:\\Program Files (x86)\\Google\\Gemini CLI\\gemini.exe",
      join(process.env.LOCALAPPDATA || "", "Google", "Gemini CLI", "gemini.exe")
    );
  } else if (isDarwin) {
    candidates.push(
      "/usr/local/bin/gemini",
      "/opt/homebrew/bin/gemini",
      join(process.env.HOME || "", ".local", "bin", "gemini")
    );
  } else {
    // Linux
    candidates.push(
      "/usr/local/bin/gemini",
      "/usr/bin/gemini",
      join(process.env.HOME || "", ".local", "bin", "gemini")
    );
  }
  
  // Check candidates
  for (const path of candidates) {
    if (existsSync(path)) {
      return path;
    }
  }
  
  // Fall back to PATH lookup
  // In a real implementation, we'd use 'which' or 'where' command
  // For now, just return "gemini" and let spawn handle PATH resolution
  return "gemini";
}

/**
 * Run a command with inherited stdio for seamless user experience.
 */
function run(cmd: string, args: string[], opts: { env: NodeJS.ProcessEnv }): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: "inherit",
      env: opts.env,
      shell: platform() === "win32"
    });
    
    child.on("exit", (code, signal) => {
      if (typeof code === "number") {
        if (code === 0) {
          resolve();
        } else {
          const error = new Error(`gemini exited with code ${code}`) as any;
          error.code = code;
          reject(error);
        }
      } else {
        reject(new Error(`gemini terminated by signal ${signal}`));
      }
    });
    
    child.on("error", (err) => {
      if ((err as any).code === "ENOENT") {
        console.error("[brainr] Error: Gemini CLI not found in PATH");
        console.error("[brainr] Please install it or set GEMINI_CLI environment variable");
      }
      reject(err);
    });
  });
}
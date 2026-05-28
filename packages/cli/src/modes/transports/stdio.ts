import { spawn } from "node:child_process";
import { platform } from "node:os";

/**
 * Default proxy transport: spawn the Python CLI "br" and stream stdio.
 * This guarantees perfect command/flag parity with zero logic duplication.
 */
export async function stdioProxy(args: string[]) {
  const cmd = process.env.BR_CLI || "br";
  await run(cmd, args, { env: process.env });
}

/**
 * Run the br CLI with inherited stdio for transparent passthrough.
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
          const error = new Error(`br exited with code ${code}`) as any;
          error.code = code;
          reject(error);
        }
      } else {
        reject(new Error(`br terminated by signal ${signal}`));
      }
    });
    
    child.on("error", (err) => {
      if ((err as any).code === "ENOENT") {
        console.error("[brainr] Error: br CLI not found");
        console.error("[brainr] Please install brain-researcher:");
        console.error("[brainr]   pip install brain-researcher");
        console.error("[brainr]   or");
        console.error("[brainr]   pipx install brain-researcher");
      }
      reject(err);
    });
  });
}
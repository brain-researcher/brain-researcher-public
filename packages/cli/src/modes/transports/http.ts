/**
 * HTTP proxy transport to a running Brain Researcher core service.
 * Forwards CLI arguments to the service and streams back the response.
 */
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { URL } from "node:url";

export async function httpProxy(baseUrl: string, args: string[]) {
  // Define the CLI proxy endpoint in the core service
  const url = new URL("/api/cli", baseUrl);
  
  // Prepare the payload with args and selected environment variables
  const payload = {
    argv: args,
    env: pickEnv([
      "OPENAI_API_KEY",
      "DEEPSEEK_API_KEY",
      "ANTHROPIC_API_KEY",
      "GEMINI_API_KEY",
      "USE_GEMINI_CLI",
      "DEFAULT_LLM_MODEL"
    ])
  };
  
  const body = JSON.stringify(payload);
  
  const isHttps = url.protocol === "https:";
  const requestFn = isHttps ? httpsRequest : httpRequest;
  
  const options = {
    method: "POST",
    hostname: url.hostname,
    port: url.port || (isHttps ? 443 : 80),
    path: url.pathname + url.search,
    headers: {
      "content-type": "application/json",
      "content-length": Buffer.byteLength(body).toString(),
      "user-agent": "@brainr/cli/0.1.0"
    }
  };
  
  await new Promise<void>((resolve, reject) => {
    const req = requestFn(options);
    
    req.on("response", (res) => {
      // Handle different response codes
      if (res.statusCode && res.statusCode >= 400) {
        let errorBody = "";
        res.on("data", (chunk) => errorBody += chunk);
        res.on("end", () => {
          console.error(`[brainr] Error: HTTP ${res.statusCode}`);
          try {
            const error = JSON.parse(errorBody);
            console.error(`[brainr] ${error.message || error.error || errorBody}`);
          } catch {
            console.error(`[brainr] ${errorBody}`);
          }
          process.exit(1);
        });
        return;
      }
      
      // Collect response and format appropriately
      let responseBody = "";
      res.on("data", (chunk) => responseBody += chunk);
      res.on("end", () => {
        try {
          const jsonResponse = JSON.parse(responseBody);
          const output = formatCliResponse(args, jsonResponse);
          process.stdout.write(output);
          if (!output.endsWith('\n')) {
            process.stdout.write('\n');
          }
        } catch (e) {
          // If not JSON, output as-is (e.g., help text)
          process.stdout.write(responseBody);
        }
        resolve();
      });
      res.on("error", reject);
    });
    
    req.on("error", (err) => {
      if ((err as any).code === "ECONNREFUSED") {
        console.error(`[brainr] Error: Cannot connect to core service at ${baseUrl}`);
        console.error("[brainr] Please ensure the service is running:");
        console.error("[brainr]   br serve agent");
        console.error("[brainr]   or");
        console.error("[brainr]   docker run ... br serve");
      } else {
        console.error(`[brainr] Error: ${err.message}`);
      }
      reject(err);
    });
    
    // Send the request
    req.write(body);
    req.end();
  });
}

/**
 * Pick specific environment variables to forward to the core service.
 * This avoids sending all env vars for security reasons.
 */
function pickEnv(keys: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const key of keys) {
    if (process.env[key]) {
      result[key] = process.env[key] as string;
    }
  }
  return result;
}

/**
 * Format CLI response based on command and flags.
 * For ask/chat commands without --json, returns just the text.
 * Otherwise returns formatted JSON.
 */
function formatCliResponse(command: string[], jsonResponse: any): string {
  const isAskOrChat = command[0] === 'ask' || command[0] === 'chat';
  const hasJsonFlag = command.includes('--json') || command.includes('-j');
  
  if (isAskOrChat && !hasJsonFlag && jsonResponse.text) {
    // For ask/chat without --json, return just the text
    return jsonResponse.text;
  }
  
  // For everything else or with --json flag, return formatted JSON
  return JSON.stringify(jsonResponse, null, 2);
}
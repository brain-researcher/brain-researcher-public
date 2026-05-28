import { httpProxy } from "./transports/http";
import { stdioProxy } from "./transports/stdio";

/**
 * Proxy to the Brain Researcher core service.
 * Decides between HTTP and stdio transport based on environment.
 */
export async function proxyCore(args: string[]) {
  const url = process.env.BR_URL || process.env.BRAINR_CORE_URL;
  
  if (url) {
    // Use HTTP transport to remote/local core service
    console.error(`[brainr] Proxying to core service at ${url}`);
    await httpProxy(url, args);
  } else {
    // Default: spawn local br CLI via stdio
    await stdioProxy(args);
  }
}
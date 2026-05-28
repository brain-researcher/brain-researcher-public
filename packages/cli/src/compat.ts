/**
 * Flag compatibility mapping between brainr and br CLI.
 * Keep this minimal - prefer pass-through for most flags.
 * Only map differences when absolutely necessary.
 */

const flagMap: Record<string, string> = {
  // Map common aliases that users might expect
  "--help": "--help",
  "-h": "--help",
  "--version": "version",
  "-v": "--verbose",
  "--verbose": "--verbose",
  
  // Model selection compatibility
  "--model": "--model",
  "-m": "-m",
  
  // Prompt compatibility
  "--prompt": "--prompt",
  "-p": "-p",
  
  // JSON output
  "--json": "--json",
  
  // For future: map any brainr-specific flags to br equivalents
  // "--foo": "--bar",
};

export function normalizeArgs(args: string[]): string[] {
  const normalized: string[] = [];
  
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    
    // Check if this flag needs mapping
    if (flagMap[arg]) {
      normalized.push(flagMap[arg]);
    } else {
      normalized.push(arg);
    }
  }
  
  return normalized;
}

/**
 * Extract command and flags for better routing in the future.
 * For now, we just pass everything through.
 */
export function parseCommand(args: string[]): {
  command?: string;
  flags: string[];
} {
  if (args.length === 0) {
    return { flags: [] };
  }
  
  // Check if first arg is a command (not a flag)
  const firstArg = args[0];
  if (!firstArg.startsWith("-")) {
    return {
      command: firstArg,
      flags: args.slice(1)
    };
  }
  
  return { flags: args };
}
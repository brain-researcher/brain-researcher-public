#!/usr/bin/env node
import { run } from "./index";

run(process.argv).catch((err: any) => {
  const code = typeof err?.code === "number" ? err.code : 1;
  const msg = String(err?.message || err || "");

  // Provide a friendlier hint for the common case where we proxied to
  // the Python CLI without a subcommand (exit code 2 from Typer).
  if (code === 2 || msg.includes("br exited with code 2")) {
    console.error("\n[brainr] hint: You ran without a command.");
    console.error("       Try one of:");
    console.error("         • brainr chat --model gemini-2.5-pro");
    console.error("         • brainr --gemini -p 'Explain fMRI in one paragraph'\n");
  }

  // Fall back to the original fatal output for debugging
  console.error("[brainr] fatal:", err?.stack || err);
  process.exit(code);
});

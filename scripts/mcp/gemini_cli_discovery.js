#!/usr/bin/env node

const { execSync } = require('node:child_process');

function readFunctions() {
  try {
    const output = execSync('npx @google/gemini-cli tools --json', {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return JSON.parse(output.toString());
  } catch (err) {
    console.error('Failed to fetch Gemini CLI tools:', err.message);
    process.exit(1);
  }
}

const tools = readFunctions();
console.log(JSON.stringify(tools, null, 2));

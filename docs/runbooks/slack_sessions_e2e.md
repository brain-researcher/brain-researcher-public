# Slack Sessions E2E Runbook

This runbook covers the v1 "neuroimage claw" path:

- wrap a real `coding_session` or `mcp_run`
- bind it to Slack
- verify status, logs, cancel, and freeform reply mirroring from your phone

## Prerequisites

- Orchestrator running and reachable
- A Slack workspace where you can create and install apps
- A public HTTPS URL for your local orchestrator, usually via `ngrok`
- CLI auth configured if your orchestrator requires bearer auth

## 1. Start orchestrator

If you are using the standalone orchestrator service:

```bash
br serve orchestrator --host 0.0.0.0 --port 3001
```

Point the CLI at it:

```bash
export ORCHESTRATOR_URL=http://127.0.0.1:3001
```

If auth is enabled, load a token:

```bash
br auth login <jwt-or-bearer-token>
```

## 2. Expose orchestrator publicly

Example with `ngrok`:

```bash
ngrok http 3001
```

Take the HTTPS forwarding URL and export it:

```bash
export BR_PUBLIC_BASE_URL=https://YOUR-NGROK-URL.ngrok-free.app
```

## 3. Render the Slack app manifest

```bash
br sessions slack-manifest --public-base-url "$BR_PUBLIC_BASE_URL" --output slack-manifest.yaml
```

Import `slack-manifest.yaml` into Slack:

- Slack API dashboard
- `Create New App`
- `From an app manifest`
- Paste the rendered YAML or upload the file

The manifest template lives at [slack_app_manifest.template.yaml](<repo>/configs/runtime/slack_app_manifest.template.yaml).

## 4. Install the Slack app

After manifest import:

- Install the app to your workspace
- Copy the bot token
- Copy the signing secret

Export them before restarting the orchestrator:

```bash
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_SIGNING_SECRET=...
```

Restart `br serve orchestrator` after setting them.

## 5. Add the app to a Slack channel

Invite the bot to the target channel:

```text
/invite @Brain Researcher
```

You need the Slack channel ID for attach. If you use Slack developer mode, Slack can show IDs directly.

## 6. Attach a real session

### Attach an MCP run

```bash
br sessions attach mcp_run run_demo \
  --display-name "Demo MCP Run" \
  --slack-channel C0123456789
```

### Attach a coding session

If you already know the orchestrator thread id:

```bash
br sessions attach coding_session thread_abc123 \
  --thread-id thread_abc123 \
  --display-name "Codex Repo Fix" \
  --slack-channel C0123456789
```

If you omit `--slack-thread-ts`, Brain Researcher posts a new root message and uses that thread for updates.

## 7. Verify from Slack and phone

Inside the Slack thread, verify:

- `status`
- `logs`
- `logs 100`
- `cancel`

Also test a freeform reply such as:

```text
Use the faster path and skip the optional refinement step.
```

That message should be mirrored into the bound Brain Researcher thread for the next continuation.

## 8. Inspect from CLI if needed

```bash
br sessions ls
br sessions get <session_id>
```

To bind Slack later instead of during attach:

```bash
br sessions bind-slack <session_id> --channel-id C0123456789
```

## Expected v1 behavior

- Status changes are posted into the Slack thread
- `status`, `logs`, and `cancel` work from Slack
- Outbound Brain Researcher thread messages mirror back into Slack when `mirror_chat` is enabled
- Freeform Slack replies are appended to the bound thread

## Troubleshooting

- `401 Invalid Slack signature`: `SLACK_SIGNING_SECRET` does not match the Slack app
- `Slack API error: not_in_channel`: invite the bot to the channel first
- No Slack callback traffic: verify the public URL in the manifest matches the current tunnel URL
- CLI cannot reach orchestrator: set `ORCHESTRATOR_URL` to the actual orchestrator base URL
- Attach works but no auth: load a token with `br auth login`

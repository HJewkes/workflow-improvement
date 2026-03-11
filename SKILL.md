---
name: workflow-improvement
description: Start background observation that watches your session for friction and implements improvements. Use when you say "start workflow improvement", "/workflow-improvement", or "watch for friction".
---

# Workflow Improvement

Team-based observation system that watches your session for friction patterns and autonomously implements improvements. The coordinator sets up the team, then moves on.

## Activation

Trigger phrases: `/workflow-improvement`, `start workflow improvement`, `watch for friction`

To stop: say `stop workflow improvement`.

## Setup Procedure

Follow these steps exactly. All bash commands are copy-paste ready.

### Step 1: Activate

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/workflow-improve.py activate
```

Parse the JSON output. You need these fields:
- `cli_path` — use this exact path for all CLI commands (setup and shutdown)
- `observer_prompt` — use this as the prompt when spawning the observer agent
- `team_name` — use this for TeamCreate and Agent spawn
- `stale_instance` — if present, its `cron_id` needs CronDelete before continuing

### Step 2: Create team and spawn observer

Do these two things:

1. **TeamCreate** with `team_name` from step 1 and description `"Watches session for friction and implements improvements"`

2. **Agent tool** to spawn the observer:
   - `team_name`: the `team_name` from step 1
   - `name`: `"observer"`
   - `subagent_type`: `"general-purpose"`
   - `run_in_background`: true
   - `prompt`: the `observer_prompt` value from step 1 (paste the entire string)

The observer will create its own wake-up cron and save the cron ID.

### Step 3: Confirm to user

Tell the user workflow improvement is active, then **stop — do not monitor the team**.

## Shutdown Procedure

When the user says "stop workflow improvement":

### Step 1: Report and archive

```bash
python3 <cli_path> report
python3 <cli_path> shutdown
```

The `report` command outputs a markdown summary. The `shutdown` command returns JSON with `cron_id` for cleanup.

### Step 2: Clean up

1. Send shutdown request to observer: `SendMessage` with `type: "shutdown_request"`, `recipient: "observer"`
2. `CronDelete` with the `cron_id` from shutdown output
3. `TeamDelete`

### Step 3: Present the report to the user

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

### Step 1: Create team and spawn observer

1. **TeamCreate** with name `"workflow-improvement"` and description `"Watches session for friction and implements improvements"`

2. **Agent tool** to spawn the observer:
   - `team_name`: the team name from TeamCreate
   - `name`: `"observer"`
   - `subagent_type`: `"general-purpose"`
   - `run_in_background`: true
   - `prompt`: `"Run python3 ${CLAUDE_SKILL_DIR}/scripts/workflow-improve.py observer-init and follow its output exactly."`

### Step 2: Confirm to user

Tell the user workflow improvement is active, then **stop — do not monitor the team**.

## Shutdown Procedure

When the user says "stop workflow improvement":

### Step 1: Report and archive

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/workflow-improve.py report
python3 ${CLAUDE_SKILL_DIR}/scripts/workflow-improve.py shutdown
```

The `report` command outputs a markdown summary. The `shutdown` command returns JSON with `cron_id` for cleanup.

### Step 2: Clean up

1. Send shutdown request to observer: `SendMessage` with `type: "shutdown_request"`, `recipient: "observer"`
2. `CronDelete` with the `cron_id` from shutdown output
3. `TeamDelete`

### Step 3: Present the report to the user
